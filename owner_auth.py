"""Revocable, in-memory owner session. Cookies contain no Instagram information."""
from __future__ import annotations
import hashlib
import secrets
import threading
import time
from engine import AppError

class OwnerAuth:
    def __init__(self, password: str, ttl: int):
        self.password_digest = hashlib.sha256(password.encode()).digest()
        self.ttl = ttl
        self.lock = threading.RLock()
        self.sid_digest = None
        self.csrf = ''
        self.expires = 0.0
        self.failures = []

    def verify_password(self, supplied: str):
        with self.lock:
            now = time.monotonic()
            self.failures = [x for x in self.failures if now - x < 900]
            if len(self.failures) >= 8:
                raise AppError('panel_attempt_limit', 429)
            digest = hashlib.sha256(supplied.encode()).digest()
            if not secrets.compare_digest(digest, self.password_digest):
                self.failures.append(now)
                raise AppError('panel_password_invalid', 401)
            self.failures.clear()

    def issue(self):
        with self.lock:
            sid = secrets.token_urlsafe(32)
            self.sid_digest = hashlib.sha256(sid.encode()).digest()
            self.csrf = secrets.token_urlsafe(32)
            self.expires = time.monotonic() + self.ttl
            return sid, self.csrf

    def check(self, sid: str):
        with self.lock:
            if (not self.sid_digest or len(sid) > 200
                    or time.monotonic() >= self.expires):
                return None
            if secrets.compare_digest(hashlib.sha256(sid.encode()).digest(), self.sid_digest):
                return self.csrf
            return None

    def revoke(self):
        with self.lock:
            self.sid_digest = None
            self.csrf = ''
            self.expires = 0.0

    def clear_if_expired(self):
        with self.lock:
            if self.sid_digest and time.monotonic() >= self.expires:
                self.revoke()
                return True
            return False
