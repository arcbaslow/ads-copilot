"""Telegram Bot API delivery. Uses httpx directly — no SDK needed for send-only."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
# Telegram limits a single message to 4096 characters.
MESSAGE_LIMIT = 4000


class TelegramError(RuntimeError):
    pass


@dataclass(slots=True)
class TelegramReporter:
    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"
    timeout: float = 30.0

    @classmethod
    def from_env(cls, bot_token_env: str, chat_id: str) -> "TelegramReporter":
        token = os.environ.get(bot_token_env)
        if not token:
            raise TelegramError(f"env var {bot_token_env} is not set")
        return cls(bot_token=token, chat_id=chat_id)

    async def send(self, text: str, client: httpx.AsyncClient | None = None) -> None:
        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        chunks = _chunk(text, MESSAGE_LIMIT)
        owns = client is None
        http = client or httpx.AsyncClient(timeout=self.timeout)
        try:
            for chunk in chunks:
                resp = await http.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "parse_mode": self.parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    raise TelegramError(
                        f"Telegram API returned {resp.status_code}: {resp.text}"
                    )
        finally:
            if owns:
                await http.aclose()


def _chunk(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.split("\n"):
        if length + len(line) + 1 > limit and current:
            out.append("\n".join(current))
            current = []
            length = 0
        current.append(line)
        length += len(line) + 1
    if current:
        out.append("\n".join(current))
    return out
