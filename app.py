"""Owner-only web edition. No public Instagram sign-up or background sending."""
from __future__ import annotations
import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from engine import AppError, Rule
from instagram_adapter import DemoAdapter, InstagramAdapter
from service import Service
from settings import Settings
from owner_auth import OwnerAuth

ROOT = Path(__file__).resolve().parent

class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(StrictBody):
    username: str = Field(pattern=r'^[A-Za-z0-9._]{1,30}$')
    owned: bool = False
    password: SecretStr = Field(min_length=1, max_length=256)
    code: SecretStr = Field(default=SecretStr(''), max_length=20)


class PostSelection(StrictBody):
    post_id: str = Field(min_length=1, max_length=100)


class Preview(PostSelection):
    keyword: str = Field(min_length=1, max_length=100)
    mode: Literal['word', 'contains', 'exact'] = 'word'
    reply: str = Field(min_length=1, max_length=1000)
    action: Literal['dm', 'comment'] = 'dm'
    tester: str = Field(pattern=r'^[A-Za-z0-9._]{1,30}$')


class Send(StrictBody):
    token: str = Field(min_length=20, max_length=100)
    confirmed: bool


class PanelLogin(StrictBody):
    password: SecretStr = Field(min_length=1, max_length=256)


def create_app(settings: Settings, *, adapter=None) -> FastAPI:
    service = Service(adapter or (DemoAdapter() if settings.demo else InstagramAdapter()), settings.data_dir)
    owner = OwnerAuth(settings.panel_password, settings.session_seconds)

    async def clear_expired():
        while True:
            await asyncio.sleep(15)
            if owner.clear_if_expired():
                await run_in_threadpool(service.disconnect)

    @asynccontextmanager
    async def lifespan(app):
        cleanup = asyncio.create_task(clear_expired())
        try:
            yield
        finally:
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup
            owner.revoke()
            await run_in_threadpool(service.disconnect)

    app = FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service, app.state.owner, app.state.settings = service, owner, settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[settings.host], www_redirect=False)

    def harden(response):
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "form-action 'self'; base-uri 'none'; object-src 'none'",
        })
        if settings.secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    def reject(code, status):
        return harden(JSONResponse({'error': code}, status_code=status))

    @app.middleware('http')
    async def security(request: Request, call_next):
        path = request.url.path
        if settings.secure and request.url.scheme != 'https' and path != '/healthz':
            return reject('https_required', 426)
        protected = path.startswith('/api/')
        sensitive = protected or path.startswith('/auth/')
        changing = request.method not in {'GET', 'HEAD', 'OPTIONS'}
        csrf = owner.check(request.cookies.get(settings.cookie_name, '')) if sensitive else None
        if sensitive:
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return reject('origin_rejected', 403)
            if protected and not csrf:
                return reject('session_required', 401)
            if changing:
                if request.headers.get('origin') != settings.origin:
                    return reject('origin_rejected', 403)
                if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    return reject('json_required', 415)
                if path != '/auth/login':
                    supplied = request.headers.get('x-csrf-token', '')
                    if not csrf or not secrets.compare_digest(supplied.encode(), csrf.encode()):
                        return reject('csrf_rejected', 403)
                data = bytearray()
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data) > 16384:
                        return reject('request_too_large', 413)
                request._body = bytes(data)
        try:
            response = await call_next(request)
        except Exception:
            return reject('internal_error', 500)
        return harden(response)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse({'error': exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({'error': 'invalid_input'}, status_code=422)

    @app.get('/healthz')
    def health():
        # Checks the ledger without exposing usernames, messages or credentials.
        with service.ledger.connect() as db:
            db.execute('SELECT 1').fetchone()
        return {'ok': True}

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    @app.get('/app.js')
    def js():
        return FileResponse(ROOT / 'static' / 'app.js', media_type='application/javascript')

    @app.get('/style.css')
    def css():
        return FileResponse(ROOT / 'static' / 'style.css', media_type='text/css')

    @app.get('/auth/status')
    def auth_status(request: Request):
        token = owner.check(request.cookies.get(settings.cookie_name, ''))
        return {'authenticated': bool(token), 'csrf': token,
                'mode': 'demo' if settings.demo else 'real'}

    @app.post('/auth/login')
    def panel_login(body: PanelLogin):
        try:
            owner.verify_password(body.password.get_secret_value())
        finally:
            body.password = SecretStr('')
        # A second owner login revokes the previous browser's authorization.
        owner.revoke()
        service.disconnect()
        sid, csrf = owner.issue()
        response = JSONResponse({'authenticated': True, 'csrf': csrf})
        response.set_cookie(settings.cookie_name, sid, max_age=settings.session_seconds,
                            secure=settings.secure, httponly=True, samesite='strict', path='/')
        return response

    @app.post('/auth/logout')
    def panel_logout():
        owner.revoke()
        service.disconnect()
        response = JSONResponse({'logged_out': True, 'instagram_session_revoked': False})
        response.delete_cookie(settings.cookie_name, path='/', secure=settings.secure,
                               httponly=True, samesite='strict')
        return response

    @app.get('/api/status')
    def status():
        return service.status()

    @app.post('/api/login')
    def login(body: Login):
        if not body.owned:
            raise AppError('ownership_confirmation_required', 403)
        if not settings.demo and body.username.casefold() != settings.owner_username.casefold():
            raise AppError('owner_account_only', 403)
        try:
            if settings.demo:
                return service.connect('demo_owner', 'not-a-real-password', '')
            return service.connect(body.username, body.password.get_secret_value(), body.code.get_secret_value())
        finally:
            body.password = SecretStr('')
            body.code = SecretStr('')

    @app.post('/api/disconnect')
    def disconnect():
        service.disconnect()
        return {'forgotten_on_server': True, 'instagram_session_revoked': False}

    @app.get('/api/posts')
    def posts():
        return {'posts': service.posts()}

    @app.post('/api/comments')
    def comments(body: PostSelection):
        return {'comments': service.comments(body.post_id), 'one_page_only': True}

    @app.post('/api/preview')
    def preview(body: Preview):
        return {'rows': service.preview(body.post_id, Rule(body.keyword, body.mode,
                        body.reply, body.action, body.tester))}

    @app.post('/api/send')
    def send(body: Send):
        return service.send(body.token, body.confirmed)

    return app
