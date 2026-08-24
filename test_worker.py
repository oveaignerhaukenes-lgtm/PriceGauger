from __future__ import annotations

from analysis_status import AnalysisStatusStore
from telegram_query_builder import build_search_plan
import worker


def _plan(message_id: str, text: str):
    return build_search_plan(
        message_id=message_id,
        message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
        text=text,
        published_at=f"2026-07-22T20:{int(message_id) % 60:02d}:00+00:00",
    )


def test_worker_fetches_all_posts_and_runs_aggregate_flow(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.db"
    plans = [
        _plan("101", "Iran missile attack on military base"),
        _plan("102", "Iran drone attack on energy infrastructure"),
    ]
    calls: list[tuple[str, int]] = []

    def fetcher(channel, *, minimum_signal):
        assert channel == "Middle_East_Spectator"
        assert minimum_signal == 0
        return list(plans)

    def refresh(**kwargs):
        calls.append((str(kwargs["channel"]), len(kwargs["plans"])))

    monkeypatch.setattr(worker, "_refresh_telegram_flow", refresh)

    summary = worker.run_once(db_path=db_path, plans_fetcher=fetcher)

    assert summary.fetched == 2
    assert summary.processed == 0
    assert summary.outcomes_refreshed == 0
    assert summary.interpreter == "retired"
    assert calls == [("Middle_East_Spectator", 2)]


def test_empty_cycle_is_valid_without_legacy_runtime(tmp_path):
    db_path = tmp_path / "empty.db"
    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: [],
    )

    assert summary.fetched == 0
    assert summary.processed == 0

    statuses = {item.step_key: item for item in AnalysisStatusStore(db_path).load()}
    assert statuses["telegram_fetch"].status == "COMPLETE"
    assert statuses["event_clustering"].status == "SKIPPED"
    assert statuses["outcome_refresh"].status == "SKIPPED"
    assert "pensjonert" in statuses["outcome_refresh"].detail


def test_worker_records_fetch_failure_but_continues_with_stored_flow(tmp_path):
    db_path = tmp_path / "failed-fetch.db"

    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("telegram")),
    )

    statuses = {item.step_key: item for item in AnalysisStatusStore(db_path).load()}
    assert summary.fetched == 0
    assert statuses["telegram_fetch"].status == "FAILED"
    assert "TimeoutError" in statuses["telegram_fetch"].detail
