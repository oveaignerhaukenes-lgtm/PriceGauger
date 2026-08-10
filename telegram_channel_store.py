from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from database import connect


DEFAULT_TELEGRAM_CHANNELS = ("Middle_East_Spectator", "tabzlive")


def normalize_telegram_channel(value: str) -> str:
    """Normalize a Telegram channel username, @handle or t.me URL."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Telegram channel cannot be empty")

    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.netloc.lower().split(":", 1)[0]
        if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            raise ValueError("Only Telegram t.me/telegram.me channel URLs are supported")
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].lower() == "s":
            parts = parts[1:]
        if not parts:
            raise ValueError("Telegram URL does not contain a channel name")
        raw = parts[0]

    channel = raw.strip().lstrip("@").strip("/")
    if not channel:
        raise ValueError("Telegram channel cannot be empty")
    if "/" in channel or any(char.isspace() for char in channel):
        raise ValueError("Telegram channel must be a channel username, @handle or t.me URL")
    return channel


class TelegramChannelStore:
    """Persistent list of enabled Telegram sources shared by UI and worker."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_channels (
                    channel TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            for channel in DEFAULT_TELEGRAM_CHANNELS:
                db.execute(
                    """
                    INSERT INTO telegram_channels(channel, enabled)
                    VALUES (?, 1)
                    ON CONFLICT(channel) DO NOTHING
                    """,
                    (channel,),
                )

    def _connect(self):
        return connect(self.path)

    def list_enabled(self) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT channel
                FROM telegram_channels
                WHERE enabled=1
                ORDER BY added_at, channel
                """
            ).fetchall()
        return [str(row["channel"]) for row in rows]

    def list_disabled(self) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT channel
                FROM telegram_channels
                WHERE enabled=0
                ORDER BY channel
                """
            ).fetchall()
        return [str(row["channel"]) for row in rows]

    def add(self, value: str) -> str:
        channel = normalize_telegram_channel(value)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_channels(channel, enabled)
                VALUES (?, 1)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled=1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (channel,),
            )
        return channel

    def disable(self, value: str) -> str:
        channel = normalize_telegram_channel(value)
        with self._connect() as db:
            db.execute(
                """
                UPDATE telegram_channels
                SET enabled=0, updated_at=CURRENT_TIMESTAMP
                WHERE channel=?
                """,
                (channel,),
            )
        return channel
