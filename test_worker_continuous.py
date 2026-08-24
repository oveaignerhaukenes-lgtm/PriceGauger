from __future__ import annotations

import inspect

from telegram_query_builder import build_search_plan
import worker


def _plan(message_id: str):
    return build_search_plan(
        message_id=message_id,
        message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
        text="Iran missile attack on energy infrastructure",
        published_at=f"2026-08-08T20:{int(message_id) % 60:02d}:00+00:00",
    )


def test_worker_has_no_legacy_per_event_runtime_authority() -> None:
    source = inspect.getsource(worker)
    for forbidden in (
        "process_market_event",
        "register_recommendations",
        "refresh_signal_outcomes",
        "MarketStateStore",
        "SignalOutcomeStore",
        "build_interpreter",
        "canonical_event_from_plan",
        "LEGACY_MAX_PER_CYCLE",
    ):
        assert forbidden not in source


def test_cycle_only_runs_aggregate_flow_after_fetch(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.db"
    plan = _plan("101")
    calls: list[str] = []

    monkeypatch.setattr(
        worker,
        "_refresh_telegram_flow",
        lambda **kwargs: calls.append("flow"),
    )

    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: [plan],
    )

    assert calls == ["flow"]
    assert summary.fetched == 1
    assert summary.pending == 0
    assert summary.processed == 0
    assert summary.outcomes_refreshed == 0


def test_scoring_failure_is_marked_and_pipeline_continues(tmp_path, monkeypatch):
    db_path = tmp_path / "scoring.db"
    plan = _plan("201")

    class FakeFlowStore:
        def __init__(self, path):
            pass

        def has_post(self, message_id):
            return False

        def load_posts(self, limit=500):
            return []

        def save_posts(self, scored):
            raise AssertionError("save_posts should not run after scoring failure")

    class FailingScorer:
        def __init__(self, api_key):
            pass

        def score(self, items):
            raise TimeoutError("scoring unavailable")

    monkeypatch.setattr(worker, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(worker, "TelegramFlowStore", FakeFlowStore)
    monkeypatch.setattr(worker, "OpenAITelegramFlowScorer", FailingScorer)

    worker._refresh_telegram_flow(
        db_path=db_path,
        channel="Middle_East_Spectator",
        plans=[plan],
    )

    statuses = {item.step_key: item for item in worker.AnalysisStatusStore(db_path).load()}
    assert statuses["telegram_scoring"].status == "FAILED"
    assert "fortsetter med tidligere lagrede poster" in statuses["telegram_scoring"].detail
    assert statuses["semantic_filter"].status == "COMPLETE"
    assert statuses["event_clustering"].status == "SKIPPED"
