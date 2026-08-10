from __future__ import annotations

from telegram_channel_store import (
    DEFAULT_TELEGRAM_CHANNELS,
    TelegramChannelStore,
    normalize_telegram_channel,
    telegram_message_key,
)


def test_channel_store_seeds_defaults_and_persists_disable(tmp_path) -> None:
    path = tmp_path / "channels.db"
    store = TelegramChannelStore(path)

    assert store.list_enabled() == list(DEFAULT_TELEGRAM_CHANNELS)

    store.disable("tabzlive")
    assert store.list_enabled() == ["Middle_East_Spectator"]

    reopened = TelegramChannelStore(path)
    assert reopened.list_enabled() == ["Middle_East_Spectator"]
    assert reopened.list_disabled() == ["tabzlive"]


def test_add_accepts_t_me_url_and_reenables_channel(tmp_path) -> None:
    store = TelegramChannelStore(tmp_path / "channels.db")
    store.disable("tabzlive")

    added = store.add("https://t.me/tabzlive")

    assert added == "tabzlive"
    assert "tabzlive" in store.list_enabled()


def test_channel_normalization_and_message_key_are_source_scoped() -> None:
    assert normalize_telegram_channel("@tabzlive") == "tabzlive"
    assert normalize_telegram_channel("https://t.me/s/tabzlive") == "tabzlive"
    assert telegram_message_key("tabzlive", "123") == "tabzlive:123"
    assert telegram_message_key("Middle_East_Spectator", "123") == "Middle_East_Spectator:123"
    assert telegram_message_key("tabzlive", "tabzlive:123") == "tabzlive:123"
