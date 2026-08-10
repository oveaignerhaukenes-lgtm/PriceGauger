from __future__ import annotations

from telegram_channel_store import TelegramChannelStore
from telegram_multi_worker import _source_aware_pairs, collect_configured_search_plans
from telegram_query_builder import TelegramSearchPlan


def _plan(message_id: str, published_at: str) -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id=message_id,
        message_url=f"https://t.me/example/{message_id}",
        message_text="Iran oil tanker update",
        event_type="event",
        target="shipping",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="iran tanker",
        signal_score=2,
        published_at=published_at,
    )


def test_collect_configured_plans_namespaces_same_local_ids(tmp_path) -> None:
    store = TelegramChannelStore(tmp_path / "channels.db")

    def fetcher(channel: str, *, minimum_signal: int, timeout: int):
        assert minimum_signal == 0
        return [_plan("42", "2026-08-10T00:00:00+00:00")]

    plans = collect_configured_search_plans(
        store,
        minimum_signal=0,
        fetcher=fetcher,
    )

    assert {plan.message_id for plan in plans} == {
        "Middle_East_Spectator:42",
        "tabzlive:42",
    }


def test_one_channel_failure_does_not_block_other_sources(tmp_path) -> None:
    store = TelegramChannelStore(tmp_path / "channels.db")

    def fetcher(channel: str, *, minimum_signal: int, timeout: int):
        if channel == "Middle_East_Spectator":
            raise RuntimeError("temporary source failure")
        return [_plan("7", "2026-08-10T00:01:00+00:00")]

    plans = collect_configured_search_plans(store, minimum_signal=0, fetcher=fetcher)

    assert [plan.message_id for plan in plans] == ["tabzlive:7"]


def test_source_aware_pairs_restore_channel_from_namespaced_id() -> None:
    tabz = _plan("tabzlive:5", "2026-08-10T00:02:00+00:00")
    spectator = _plan("Middle_East_Spectator:9", "2026-08-10T00:03:00+00:00")

    resolved = _source_aware_pairs(
        [("configured-sources", tabz), ("configured-sources", spectator)]
    )

    assert [channel for channel, _ in resolved] == ["tabzlive", "Middle_East_Spectator"]
