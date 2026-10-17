# Replya Web 0.2 - one-owner test edition

**Status:** source package and offline preview, NOT an already-hosted URL. This package does not modify the previous ChatGPT-hosted Replya site. No Instagram account was used during development.

Start with `START-HERE-fa.txt` for the Persian quick guide.

## Included

- `replya-preview.html`: self-contained, offline, simulated browser preview. No password or server is needed. Its data is fictional and resets when reopened. Its small JavaScript matcher is for demonstration; the server's Python engine is the authoritative implementation.
- `app.py`, `settings.py`, `owner_auth.py`: web API, owner authentication, configured HTTPS origin, revocable one-hour cookie session and CSRF protection.
- `engine.py`, `service.py`, `instagram_adapter.py`: the original own-account keyword-test workflow, with explicit confirmation for every send.
- `static/`: responsive Persian interface. In demo mode the actual Instagram password fields are hidden.
- `render.yaml`: deployment configuration for a single Python web service with a persistent disk. It uses PAID resources; review Render's current price before approving creation. No service was purchased or deployed.
- `Dockerfile`: optional container deployment. The Render configuration uses its native Python runtime instead.
- `tests/`, `TEST-RESULTS.json`: tests and precise verification scope.

## Local demo

Use Python 3.10 or newer. On Windows run `start-demo-windows.bat`, or run:

```sh
python -m venv .venv
# Activate the environment using the command for your operating system.
python -m pip install -r requirements-core.txt
python run.py
```

Open the loopback URL printed in the terminal, then enter the generated panel password printed there. That is NOT an Instagram password. `run.py` deliberately starts demo mode only. Alternatively open the standalone HTML for a demo without Python.

## Deploy the web app

1. Upload this folder's CONTENTS to a private repository you own, with `render.yaml` at the repository root. Do not upload `.env`, SQLite data, cookies, logs, or passwords.
2. Connect the repository to Render and create a Blueprint using `render.yaml`. Review compute and disk charges before approving it. This package does not include a pre-created repository or service.
3. The configuration starts in `REPLYA_MODE=demo`. Render supplies `RENDER_EXTERNAL_URL`; the app uses it as its only permitted public origin. A custom domain requires `PUBLIC_URL=https://your-exact-domain` and a verified TLS configuration.
4. Find the generated `PANEL_PASSWORD` in YOUR hosting dashboard. Do not paste it in chat. Open the service's actual HTTPS address and log in with that secret.
5. Test demo posts, comments, keyword preview and simulated sending first.
6. To attempt your own Instagram account, set `OWNER_IG_USERNAME` to your own exact username and `REPLYA_MODE=real`, then redeploy. The persistent disk must be mounted and `DATA_DIR` must be writable. `PERSISTENT_DATA=1` is your configuration acknowledgment, not automatic proof that a volume is durable.
7. Enter your Instagram password only in your own HTTPS-hosted, authenticated panel. Use a second account you control as the named tester. Read a post, read comments, preview the rule, then explicitly confirm ONE response. Verify actual receipt in Instagram yourself.

Do not enable real mode with an ephemeral ledger: restarts could otherwise lose duplicate-send protection and daily attempt counts. Do not deploy additional instances, background workers or multiple Uvicorn workers; account sessions and preview tokens are intentionally in one process.

## Security and operational boundaries

- This is an experimental, single-owner tool, not a multi-tenant SaaS or an assurance of production security.
- No registration page, shared client accounts, automatic sending, polling, CAPTCHA bypass, proxy rotation, or anti-detection behavior is implemented.
- A successful owner login invalidates the previous browser session. Sessions expire after one hour. Logout clears the local server's account reference; expiration cleanup runs every 15 seconds. Clearing references is not a guarantee of RAM zeroization or Instagram-side session revocation.
- The code does not intentionally persist or log Instagram passwords or session cookies. The session is held temporarily in server RAM. Configure your host and observability services not to capture request bodies or dumps. The host necessarily processes requests and must be trusted.
- Persistent SQLite files hold attempt keys, account IDs, action types, dates and states. They do not store comment bodies or message text. Keep that directory private.
- There is a five-attempt daily UTC cap per account; failed/ambiguous send attempts count. This is only an application limit, not an Instagram-approved rate or a guarantee against restrictions.
- The library is unofficial. Instagram can reject login, require verification, restrict an account, or change endpoints. Resolve verification in Instagram's official app; this tool stops instead of bypassing it.
- `api_accepted` does not prove the recipient received a message. Check Instagram. Ambiguous sends are deliberately not retried automatically.
- Keep the configured exact HTTPS origin and private panel secret. No wildcard CORS is configured. Secret values belong in the host environment, never client-side files.
- The supplied server command trusts forwarded protocol headers ONLY because it is intended behind Render's HTTPS proxy. For other hosts, configure trusted proxy addresses correctly and do not expose the backend directly to the public internet.
- Docker runs as UID 10001. An external data volume must be writable by that user; prepare its ownership before startup. The Docker image and cloud build were not executed in this environment.
- Pinning direct dependencies is not a complete supply-chain audit. Review dependency advisories and test updates before production.

## Verification

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The backend was tested using FastAPI TestClient. The interface was exercised with Chromium and a local TestClient fetch bridge because direct browser navigation to the local test port was blocked by the environment. The standalone preview was rendered with Chromium `set_content`. These are not tests of actual cloud networking, reverse-proxy behavior, Docker builds, or a real Instagram login. See `TEST-RESULTS.json` for exact results.

## Primary documentation checked

- https://render.com/docs/web-services
- https://render.com/docs/blueprint-spec
- https://render.com/docs/disks
- https://render.com/docs/environment-variables
- https://www.starlette.io/middleware/
- https://pypi.org/project/instagrapi/3.0.26/

Configuration was prepared on 2026-10-18. Recheck host pricing and requirements before deploying.
