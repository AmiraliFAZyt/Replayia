"""Single-account test workflow and durable, fail-closed send ledger."""
from __future__ import annotations
import hashlib
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from engine import AppError, Rule, matches


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS attempts (
                event_key TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                utc_day TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL)''')
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def day():
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')

    def state(self, key: str):
        with self.connect() as db:
            row = db.execute('SELECT state FROM attempts WHERE event_key=?', (key,)).fetchone()
        return row[0] if row else None

    def count(self, account: str) -> int:
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM attempts WHERE account_id=? AND utc_day=?',
                              (account, self.day())).fetchone()[0]

    def reserve(self, key: str, account: str, action: str) -> None:
        # Committed before any network write. Ambiguous requests are never replayed.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM attempts WHERE event_key=?', (key,)).fetchone():
                raise AppError('already_attempted', 409)
            count = db.execute('SELECT COUNT(*) FROM attempts WHERE account_id=? AND utc_day=?',
                               (account, self.day())).fetchone()[0]
            if count >= 5:
                raise AppError('test_limit', 429)
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',
                       (key, account, self.day(), action, 'pending', time.time()))

    def finish(self, key: str, state: str) -> None:
        with self.connect() as db:
            db.execute('UPDATE attempts SET state=? WHERE event_key=?', (state, key))


class Service:
    def __init__(self, adapter, data_dir: Path):
        self.adapter = adapter
        # Separate demo and real ledgers, never mix simulated receipts with real ones.
        self.ledger = Ledger(data_dir / ('ledger-' + adapter.mode + '.sqlite3'))
        self.lock = threading.RLock()
        self.account = None
        self.paused = None
        self.posts_cache = {}
        self.comment_cache = {}
        self.drafts = {}
        self.login_tries = []
        self.last_read = 0.0

    def status(self):
        with self.lock:
            return {'mode': self.adapter.mode, 'account': self.account,
                    'paused': self.paused, 'limit': 5,
                    'attempts_today': self.ledger.count(self.account['id']) if self.account else 0}

    def ready(self):
        if self.paused:
            raise AppError(self.paused, 409)
        if not self.account:
            raise AppError('not_connected', 409)

    def _guard_read(self):
        # UI abuse guard, not an evasion tactic or an Instagram-safe rate claim.
        now = time.monotonic()
        if self.adapter.mode != 'demo' and now - self.last_read < 2:
            raise AppError('request_busy', 429)
        self.last_read = now

    def _network(self, fn, *args):
        try:
            return fn(*args)
        except AppError as e:
            if e.code in {'verification_required', 'restricted', 'login_required',
                          'credentials_rejected', 'instagram_error'}:
                self.paused = e.code
            raise

    def connect(self, username: str, password: str, code: str = ''):
        with self.lock:
            now = time.monotonic()
            self.login_tries = [t for t in self.login_tries if now - t < 900]
            if len(self.login_tries) >= 3:
                raise AppError('login_attempt_limit', 429)
            self.login_tries.append(now)
            self.disconnect()
            try:
                self.account = self.adapter.login(username, password, code)
            except AppError as exc:
                self.paused = exc.code if exc.code != 'two_factor_required' else None
                raise
            return self.status()

    def disconnect(self):
        with self.lock:
            self.adapter.close()
            self.account = None
            self.paused = None
            self.posts_cache.clear()
            self.comment_cache.clear()
            self.drafts.clear()
            self.last_read = 0

    def posts(self):
        with self.lock:
            self.ready()
            self._guard_read()
            posts = self._network(self.adapter.posts)
            self.posts_cache = {p['id']: p for p in posts}
            self.comment_cache.clear()
            self.drafts.clear()
            return posts

    def comments(self, post_id: str):
        with self.lock:
            self.ready()
            if post_id not in self.posts_cache:
                raise AppError('not_owned', 403)
            self._guard_read()
            rows = self._network(self.adapter.comments, post_id)
            self.comment_cache = {post_id: (time.monotonic(), rows)}
            self.drafts.clear()
            return rows

    def preview(self, post_id: str, rule: Rule):
        rule.validate()
        with self.lock:
            self.ready()
            record = self.comment_cache.get(post_id)
            if not record or time.monotonic() - record[0] > 600:
                raise AppError('read_comments_first', 409)
            self.drafts.clear()
            rows = []
            for c in record[1]:
                reason = None
                if c['user_id'] == self.account['id']:
                    reason = 'own_comment'
                elif c['username'].casefold() != rule.tester.casefold():
                    reason = 'not_tester'
                elif not matches(c['text'], rule.keyword, rule.mode):
                    reason = 'no_match'
                key = hashlib.sha256('|'.join((self.account['id'], post_id, c['id'], rule.action)).encode()).hexdigest()
                if not reason and self.ledger.state(key):
                    reason = 'already_attempted'
                row = {'comment_id': c['id'], 'username': c['username'],
                       'text': c['text'], 'reason': reason, 'action': rule.action}
                if not reason:
                    token = secrets.token_urlsafe(24)
                    draft = {'key': key, 'created': time.monotonic(),
                             'account_id': self.account['id'], 'post_id': post_id,
                             'comment_id': c['id'], 'user_id': c['user_id'],
                             'username': c['username'], 'action': rule.action,
                             'reply': rule.reply.replace('{username}', c['username'])}
                    self.drafts[token] = draft
                    row.update(token=token, reply=draft['reply'])
                rows.append(row)
            return rows

    def send(self, token: str, confirmed: bool):
        with self.lock:
            self.ready()
            if confirmed is not True:
                raise AppError('confirmation_required', 400)
            draft = self.drafts.get(token)
            if not draft or time.monotonic() - draft['created'] > 600:
                raise AppError('expired_preview', 409)
            if draft['account_id'] != self.account['id']:
                raise AppError('account_mismatch', 409)
            self.ledger.reserve(draft['key'], self.account['id'], draft['action'])
            self.drafts.pop(token, None)
            try:
                receipt = self._network(self.adapter.send, draft)
            except Exception:
                # A timeout/error may happen AFTER Instagram accepted the message.
                self.ledger.finish(draft['key'], 'unknown')
                self.paused = self.paused or 'delivery_unknown'
                raise AppError('delivery_unknown', 409) from None
            self.ledger.finish(draft['key'], 'accepted')
            return {'state': 'demo_only' if self.adapter.mode == 'demo' else 'api_accepted',
                    'receipt_id': receipt, 'action': draft['action'],
                    'recipient': draft['username'], 'delivery_verified': False}
