from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from typing import Protocol, Sequence

import requests
from bs4 import BeautifulSoup

_CHANNEL_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?(?P<name>[A-Za-z0-9_]+)")


@dataclass(frozen=True, slots=True)
class SourceMessage:
    source: str
    channel: str
    message_id: str
    message_url: str
    text: str
    published_at: str = ""
    edited_at: str = ""
    raw_payload: object | None = None


class MessageSource(Protocol):
    async def fetch(self) -> list[SourceMessage]:
        """Return currently available messages from all configured channels."""


def normalize_channel(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("Telegram channel cannot be empty")
    match = _CHANNEL_RE.fullmatch(candidate.rstrip("/"))
    if match:
        return match.group("name")
    return candidate.lstrip("@").strip("/")


def normalize_channels(values: str | Sequence[str]) -> tuple[str, ...]:
    raw = values.split(",") if isinstance(values, str) else values
    channels = tuple(dict.fromkeys(normalize_channel(value) for value in raw if str(value).strip()))
    if not channels:
        raise ValueError("At least one Telegram channel is required")
    return channels


def _messages_from_public_html(html: str) -> list[SourceMessage]:
    soup = BeautifulSoup(html, "html.parser")
    messages: list[SourceMessage] = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        text_node = wrap.select_one(".tgme_widget_message_text")
        time_node = wrap.select_one("time")
        if post is None or text_node is None:
            continue
        data_post = str(post.get("data-post") or "")
        if "/" not in data_post:
            continue
        channel, message_id = data_post.rsplit("/", 1)
        text = text_node.get_text("\n", strip=True)
        if not text:
            continue
        messages.append(
            SourceMessage(
                source="telegram-web",
                channel=channel,
                message_id=message_id,
                message_url=f"https://t.me/{channel}/{message_id}",
                text=text,
                published_at=str(time_node.get("datetime") or "") if time_node else "",
            )
        )
    return messages


class TelegramWebSource:
    """No-login adapter for public Telegram preview pages."""

    def __init__(self, channels: str | Sequence[str], *, timeout: int = 30) -> None:
        self.channels = normalize_channels(channels)
        self.timeout = timeout

    def _fetch_channel(self, channel: str) -> list[SourceMessage]:
        response = requests.get(
            f"https://t.me/s/{channel}",
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 PriceGauger/1.3"},
        )
        response.raise_for_status()
        return _messages_from_public_html(response.text)

    async def fetch(self) -> list[SourceMessage]:
        batches = await asyncio.gather(
            *(asyncio.to_thread(self._fetch_channel, channel) for channel in self.channels)
        )
        messages = [message for batch in batches for message in batch]
        return sorted(messages, key=lambda item: (item.published_at, item.channel, item.message_id))


class TelethonSource:
    """Full Telegram adapter using the user's own Telegram account session.

    Telethon is imported lazily, so public web mode works without installing it.
    The first account-mode run asks for the Telegram login code and stores a
    local session file. TELEGRAM_API_ID and TELEGRAM_API_HASH identify the app;
    the session identifies the individual user.
    """

    def __init__(
        self,
        channels: str | Sequence[str],
        *,
        api_id: int | None = None,
        api_hash: str | None = None,
        session_path: str | None = None,
        limit_per_channel: int = 100,
    ) -> None:
        self.channels = normalize_channels(channels)
        self.api_id = int(api_id or os.environ.get("TELEGRAM_API_ID", "0"))
        self.api_hash = api_hash or os.environ.get("TELEGRAM_API_HASH", "")
        self.session_path = session_path or os.environ.get(
            "TELEGRAM_SESSION_PATH", ".data/pricegauger-telegram"
        )
        self.limit_per_channel = limit_per_channel
        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Account mode requires TELEGRAM_API_ID and TELEGRAM_API_HASH"
            )

    async def fetch(self) -> list[SourceMessage]:
        try:
            from telethon import TelegramClient
        except ImportError as exc:
            raise RuntimeError(
                "Account mode requires Telethon. Install with: pip install telethon"
            ) from exc

        messages: list[SourceMessage] = []
        async with TelegramClient(self.session_path, self.api_id, self.api_hash) as client:
            for channel in self.channels:
                async for item in client.iter_messages(channel, limit=self.limit_per_channel):
                    text = str(getattr(item, "message", "") or "").strip()
                    if not text:
                        continue
                    published = getattr(item, "date", None)
                    edited = getattr(item, "edit_date", None)
                    messages.append(
                        SourceMessage(
                            source="telethon",
                            channel=channel,
                            message_id=str(item.id),
                            message_url=f"https://t.me/{channel}/{item.id}",
                            text=text,
                            published_at=_iso_utc(published),
                            edited_at=_iso_utc(edited),
                            raw_payload=item,
                        )
                    )
        return sorted(messages, key=lambda item: (item.published_at, item.channel, item.message_id))


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def build_telegram_source(
    mode: str,
    channels: str | Sequence[str],
    **kwargs,
) -> MessageSource:
    selected = str(mode or "web").strip().lower()
    if selected == "web":
        return TelegramWebSource(channels, timeout=int(kwargs.get("timeout", 30)))
    if selected in {"account", "telethon"}:
        return TelethonSource(
            channels,
            api_id=kwargs.get("api_id"),
            api_hash=kwargs.get("api_hash"),
            session_path=kwargs.get("session_path"),
            limit_per_channel=int(kwargs.get("limit_per_channel", 100)),
        )
    raise ValueError(f"Unsupported Telegram source mode: {mode!r}")
