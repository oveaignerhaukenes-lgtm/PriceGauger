from __future__ import annotations

import asyncio

from telegram_ingestion import plans_from_messages
from telegram_sources import (
    SourceMessage,
    TelegramWebSource,
    _messages_from_public_html,
    normalize_channel,
    normalize_channels,
)


def test_channel_links_and_names_normalize_to_same_identifier() -> None:
    assert normalize_channel("@Middle_East_Spectator") == "Middle_East_Spectator"
    assert normalize_channel("https://t.me/Middle_East_Spectator") == "Middle_East_Spectator"
    assert normalize_channel("https://t.me/s/Middle_East_Spectator/") == "Middle_East_Spectator"


def test_multiple_channels_are_deduplicated_in_input_order() -> None:
    channels = normalize_channels(
        "@Middle_East_Spectator,https://t.me/Middle_East_Spectator,Other_Channel"
    )
    assert channels == ("Middle_East_Spectator", "Other_Channel")


def test_public_html_maps_to_neutral_source_messages() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/41"></div>
      <div class="tgme_widget_message_text">Missile attack on an Iranian refinery.</div>
      <time datetime="2026-07-25T18:10:00+00:00"></time>
    </div>
    """
    messages = _messages_from_public_html(html)
    assert messages == [
        SourceMessage(
            source="telegram-web",
            channel="Middle_East_Spectator",
            message_id="41",
            message_url="https://t.me/Middle_East_Spectator/41",
            text="Missile attack on an Iranian refinery.",
            published_at="2026-07-25T18:10:00+00:00",
        )
    ]


def test_message_ids_include_channel_to_prevent_cross_channel_collisions() -> None:
    messages = [
        SourceMessage(
            source="telegram-web",
            channel="Channel_A",
            message_id="10",
            message_url="https://t.me/Channel_A/10",
            text="Missile attack on an Iranian refinery.",
        ),
        SourceMessage(
            source="telegram-web",
            channel="Channel_B",
            message_id="10",
            message_url="https://t.me/Channel_B/10",
            text="Missile attack on an Iranian refinery.",
        ),
    ]
    plans = plans_from_messages(messages)
    assert [plan.message_id for plan in plans] == ["Channel_A:10", "Channel_B:10"]


def test_web_source_fetches_all_configured_channels(monkeypatch) -> None:
    source = TelegramWebSource(("Channel_A", "Channel_B"))

    def fake_fetch(channel: str):
        return [
            SourceMessage(
                source="telegram-web",
                channel=channel,
                message_id="1",
                message_url=f"https://t.me/{channel}/1",
                text="Missile attack on an Iranian refinery.",
                published_at=f"2026-07-25T18:10:0{0 if channel == 'Channel_A' else 1}+00:00",
            )
        ]

    monkeypatch.setattr(source, "_fetch_channel", fake_fetch)
    messages = asyncio.run(source.fetch())
    assert [message.channel for message in messages] == ["Channel_A", "Channel_B"]
