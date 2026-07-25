from __future__ import annotations

import asyncio

from event_resolution import canonical_event_from_plan
from telegram_ingestion import plans_from_messages
from telegram_query_builder import build_search_plan
from telegram_sources import (
    SourceMessage,
    TelegramWebSource,
    _messages_from_public_html,
    normalize_channel,
    normalize_channels,
)
from worker import WorkerStateStore, _pending_plans, _state_message_id


def test_channel_links_and_names_normalize_to_same_identifier() -> None:
    assert normalize_channel("@Middle_East_Spectator") == "Middle_East_Spectator"
    assert normalize_channel("https://t.me/Middle_East_Spectator") == "Middle_East_Spectator"
    assert normalize_channel("https://t.me/s/Middle_East_Spectator/") == "Middle_East_Spectator"


def test_multiple_channels_are_deduplicated_in_input_order() -> None:
    channels = normalize_channels(
        "@Middle_East_Spectator,https://t.me/Middle_East_Spectator,Other_Channel"
    )
    assert channels == ("Middle_East_Spectator", "Other_Channel")


def test_public_html_preserves_publication_timestamp() -> None:
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


def test_plans_keep_raw_message_id_while_worker_identity_includes_channel() -> None:
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
    assert [plan.message_id for plan in plans] == ["10", "10"]
    assert [_state_message_id(plan) for plan in plans] == ["Channel_A:10", "Channel_B:10"]


def test_canonical_event_id_does_not_repeat_channel() -> None:
    plan = build_search_plan(
        message_id="35468",
        message_url="https://t.me/Middle_East_Spectator/35468",
        text="Missile attack on an Iranian refinery.",
        published_at="2026-07-25T20:40:00+00:00",
    )
    event = canonical_event_from_plan(plan)
    assert event.event_id == "telegram:Middle_East_Spectator:35468"
    assert event.published_at == "2026-07-25T20:40:00+00:00"


def test_source_bootstrap_skips_backlog_and_recognizes_legacy_ids(tmp_path) -> None:
    state = WorkerStateStore(tmp_path / "worker.db")
    state.mark("35460", "processed")
    plans = [
        build_search_plan(
            message_id=str(message_id),
            message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
            text="Missile attack on an Iranian refinery.",
        )
        for message_id in (35460, 35463, 35468)
    ]

    pending, ignored = _pending_plans(
        plans,
        state,
        source_key="telegram:web:Middle_East_Spectator",
    )

    assert [plan.message_id for plan in pending] == ["35468"]
    assert [plan.message_id for plan in ignored] == ["35463"]


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
