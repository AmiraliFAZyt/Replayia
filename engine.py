"""Small, deterministic rule engine. No network calls and no AI model."""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass


class AppError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).casefold()
    text = text.translate(str.maketrans({
        '\u064a': '\u06cc', '\u0649': '\u06cc', '\u0643': '\u06a9',
        '\u200c': ' ', '\u200d': ' ', '\ufeff': '', '\u0640': '',
        **{chr(0x6f0+i): str(i) for i in range(10)},
        **{chr(0x660+i): str(i) for i in range(10)},
    }))
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', text).strip()


def matches(text: str, keyword: str, mode: str) -> bool:
    text, keyword = normalize(text), normalize(keyword)
    if not keyword:
        return False
    if mode == 'exact':
        return text == keyword
    if mode == 'contains':
        return keyword in text
    if mode == 'word':
        return re.search(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', text) is not None
    raise AppError('invalid_match_mode')


@dataclass(frozen=True)
class Rule:
    keyword: str
    mode: str
    reply: str
    action: str
    tester: str

    def validate(self) -> None:
        if not 1 <= len(normalize(self.keyword)) <= 100:
            raise AppError('invalid_keyword')
        if self.mode not in {'word', 'exact', 'contains'}:
            raise AppError('invalid_match_mode')
        if not self.reply.strip() or len(self.reply) > 1000:
            raise AppError('invalid_reply')
        if self.action not in {'dm', 'comment'}:
            raise AppError('invalid_action')
        if not re.fullmatch(r'[A-Za-z0-9._]{1,30}', self.tester):
            raise AppError('invalid_tester')
