"""instagrapi adapter. Only an explicitly logged-in owner's posts are exposed.
No browser-cookie import, proxy rotation, CAPTCHA service, or challenge bypass.
Dependencies are loaded only when real mode is used; demo/tests are offline.
"""
from __future__ import annotations
import logging
from typing import Any
from engine import AppError


class ManualVerification(Exception):
    pass


def _manual_only(*args: Any, **kwargs: Any) -> None:
    raise ManualVerification('Complete verification in the official Instagram app.')


def _client_factory() -> Any:
    try:
        from instagrapi import Client
    except ImportError:
        raise AppError('dependency_missing', 503) from None

    class NoChallengeClient(Client):
        def challenge_resolve(self, *args: Any, **kwargs: Any) -> Any:
            _manual_only()

    # Never expose third-party request logs or exception payloads containing secrets.
    for name in ('instagrapi', 'private_request', 'public_request'):
        log = logging.getLogger(name)
        log.handlers = [logging.NullHandler()]
        log.propagate = False
        log.disabled = True
    client = NoChallengeClient(
        session_retry_total=0,
        public_request_retries_count=0,
        tls_verify=True,
    )
    client.challenge_code_handler = _manual_only
    client.change_password_handler = _manual_only
    return client


def error_code(exc: Exception) -> str:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if isinstance(exc, ManualVerification):
        return 'verification_required'
    if names & {'TwoFactorRequired'}:
        return 'two_factor_required'
    if any(n.startswith(('Challenge', 'Recaptcha', 'Checkpoint')) for n in names):
        return 'verification_required'
    if names & {'FeedbackRequired', 'PleaseWaitFewMinutes', 'SentryBlock',
                'ClientThrottledError', 'RateLimitError'}:
        return 'restricted'
    if names & {'BadPassword', 'LoginBadPassword'}:
        return 'credentials_rejected'
    if names & {'LoginRequired', 'ClientLoginRequired', 'AccountSuspended'}:
        return 'login_required'
    if names & {'DirectMessageRequestsDisabled'}:
        return 'recipient_unavailable'
    if getattr(getattr(exc, 'response', None), 'status_code', None) == 429:
        return 'restricted'
    return 'instagram_error'


class InstagramAdapter:
    mode = 'real'

    def __init__(self, client_factory=None):
        self._factory = client_factory or _client_factory
        self.client = None
        self.account_id = ''
        self.username = ''

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AppError:
            raise
        except Exception as exc:
            # Do not return exception repr, str(exc), cookies, response, or headers.
            raise AppError(error_code(exc), 409) from None

    def login(self, username: str, password: str, code: str = '') -> dict:
        self.close()
        client = self._factory()
        try:
            ok = self._call(client.login, username, password, verification_code=code)
            if not ok or not client.user_id:
                raise AppError('login_required', 409)
            # A real read validates the account, not merely a successful boolean.
            account = self._call(client.account_info)
            if str(account.pk) != str(client.user_id):
                raise AppError('account_mismatch', 409)
            self.client = client
            self.account_id = str(account.pk)
            self.username = str(account.username)
            return {'id': self.account_id, 'username': self.username}
        finally:
            # Best-effort reference removal, not a guarantee of RAM zeroization.
            client.password = ''
            password = ''
            code = ''

    def posts(self) -> list[dict]:
        rows = self._call(self.client.user_medias_v1, self.account_id, amount=12)
        return [
            {'id': str(m.id), 'caption': (m.caption_text or '')[:240],
             'code': str(m.code), 'comments': int(m.comment_count or 0)}
            for m in rows[:12] if str(m.user.pk) == self.account_id
        ]

    def comments(self, post_id: str) -> list[dict]:
        media = self._call(self.client.media_info_v1, post_id)
        if str(media.user.pk) != self.account_id:
            raise AppError('not_owned', 403)
        # Only one returned page, not an unbounded whole-account crawler.
        result = self._call(self.client.media_comments_v1_chunk, post_id)
        comments = result[0]
        return [{'id': str(c.pk), 'text': (c.text or '')[:3000],
                 'user_id': str(c.user.pk), 'username': str(c.user.username)}
                for c in comments[:50] if c.user is not None]

    def send(self, draft: dict) -> str:
        if draft['action'] == 'comment':
            result = self._call(self.client.media_comment, draft['post_id'],
                                draft['reply'],
                                replied_to_comment_id=int(draft['comment_id']))
        else:
            result = self._call(self.client.direct_send, draft['reply'],
                                user_ids=[int(draft['user_id'])])
        receipt = getattr(result, 'id', None) or getattr(result, 'pk', None)
        if not receipt:
            raise AppError('unconfirmed_result', 502)
        return str(receipt)

    def close(self) -> None:
        # Local forgetting only. This does NOT claim to revoke a server session.
        client, self.client = self.client, None
        self.account_id, self.username = '', ''
        if client is not None:
            client.password = ''
            for attr in ('private', 'public'):
                session = getattr(client, attr, None)
                if session is not None:
                    session.cookies.clear()
                    session.close()


class DemoAdapter:
    """Clearly marked fixture. Never contacts Instagram."""
    mode = 'demo'

    def __init__(self):
        self.account_id = ''
        self.username = ''
        self.sent = []

    def login(self, username: str, password: str, code: str = '') -> dict:
        self.account_id, self.username = '900001', 'demo_owner'
        return {'id': self.account_id, 'username': self.username}

    def posts(self) -> list[dict]:
        return [{'id': '10001_900001', 'caption': '\u067e\u0633\u062a \u0622\u0632\u0645\u0627\u06cc\u0634\u06cc \u0631\u06cc\u067e\u0644\u0627\u06cc\u0627',
                 'code': 'DEMO_ONLY', 'comments': 3}]

    def comments(self, post_id: str) -> list[dict]:
        if post_id != '10001_900001':
            raise AppError('not_owned', 403)
        return [
            {'id': '2001', 'user_id': '900002', 'username': 'demo_tester',
             'text': '\u0633\u0644\u0627\u0645\u060c \u0642\u06cc\u0645\u062a\u061f'},
            {'id': '2002', 'user_id': '900003', 'username': 'other_user',
             'text': '\u0642\u06cc\u0645\u062a'},
            {'id': '2003', 'user_id': '900002', 'username': 'demo_tester',
             'text': '\u0639\u0627\u0644\u06cc\u0647'},
        ]

    def send(self, draft: dict) -> str:
        self.sent.append(dict(draft))
        return 'demo-receipt-' + str(len(self.sent))

    def close(self) -> None:
        self.account_id = self.username = ''
