"""Local browser preview; the cloud entrypoint is server:app."""
import argparse
import secrets
from pathlib import Path
import uvicorn
from app import create_app
from settings import Settings

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535.')
    origin = 'http://127.0.0.1:' + str(args.port)
    password = secrets.token_urlsafe(32)
    print('DEMO ONLY | Open ' + origin)
    print('Panel password (NOT your Instagram password): ' + password, flush=True)
    settings = Settings(origin, password, Path(__file__).parent / 'data', allow_local_http=True)
    uvicorn.run(create_app(settings), host='127.0.0.1', port=args.port, access_log=False, log_level='critical')
