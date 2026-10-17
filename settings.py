"""Configuration for one owner, one process and one persistent ledger."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Settings:
    origin: str
    panel_password: str = field(repr=False)
    data_dir: Path
    demo: bool = True
    owner_username: str = ''
    allow_local_http: bool = False
    persistent_data_confirmed: bool = False
    session_seconds: int = 3600

    def __post_init__(self):
        url = urlsplit(self.origin)
        local = url.hostname in {'localhost', '127.0.0.1'}
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path not in {'', '/'} or url.scheme not in {'http', 'https'}):
            raise ValueError('PUBLIC_URL must be a single origin without path or credentials.')
        if url.scheme != 'https' and not (self.allow_local_http and local):
            raise ValueError('HTTPS is required outside an explicit loopback-only test.')
        if (len(self.panel_password) < 32 or len(self.panel_password) > 256
                or self.panel_password.startswith('REPLACE_')):
            raise ValueError('PANEL_PASSWORD must be a random secret of 32-256 characters.')
        if not self.demo:
            if not re.fullmatch(r'[A-Za-z0-9._]{1,30}', self.owner_username):
                raise ValueError('Set OWNER_IG_USERNAME before enabling real mode.')
            if not self.persistent_data_confirmed:
                raise ValueError('Real mode requires a persistent data directory. See README.')
        if not 60 <= self.session_seconds <= 3600:
            raise ValueError('Session duration must be between 60 and 3600 seconds.')
        object.__setattr__(self, 'origin', url.scheme + '://' + url.netloc.lower())

    @property
    def secure(self):
        return self.origin.startswith('https://')

    @property
    def host(self):
        return urlsplit(self.origin).hostname

    @property
    def cookie_name(self):
        return '__Host-replya' if self.secure else 'replya-local'

    @classmethod
    def from_env(cls):
        mode = os.environ.get('REPLYA_MODE', 'demo')
        if mode not in {'demo', 'real'}:
            raise ValueError('REPLYA_MODE must be demo or real.')
        return cls(
            origin=os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL', ''),
            panel_password=os.environ.get('PANEL_PASSWORD', ''),
            data_dir=Path(os.environ.get('DATA_DIR', '/var/data/replya')),
            demo=mode == 'demo',
            owner_username=os.environ.get('OWNER_IG_USERNAME', ''),
            allow_local_http=os.environ.get('ALLOW_LOCAL_HTTP') == '1',
            persistent_data_confirmed=os.environ.get('PERSISTENT_DATA') == '1',
        )
