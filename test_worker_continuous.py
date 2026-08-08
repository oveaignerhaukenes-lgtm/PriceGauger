from __future__ import annotations

from types import SimpleNamespace

from market_interpreter import MockMarketInterpreter
from telegram_query_builder import build_search_plan
import worker


def _plan(message_id: str):
    return build_search_plan(
        message_id=message_id,
        message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
        text="Iran missile attack on energy infrastructure",
        published_at=f"2026-08-08T20:{int(message_id) % 60:02d}:00+00:00",
    )


def test_fresh_flow_runs_before_failing_legacy_event(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.db"
    plan = _plan("101")
    calls: list[str] = []

    monkeypatch.setattr(
        worker,
        "_refresh_telegram_flow",
        lambda **kwargs: calls.append("flow"),
    )

    def fail_legacy(*args, **kwargs):
        calls.append("legacy")
        raise RuntimeError("bad legacy response")

    monkeypatch.setattr(worker, "process_market_event", fail_legacy)
    monkeypatch.setattr(worker, "refresh_signal_outcomes", lambda **kwargs: [])

    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: [plan],
        interpreter=MockMarketInterpreter(),
    )

    assert calls == ["flow", "legacy"]
    assert summary.pending == 1
    assert summary.processed == 0
    state = worker.WorkerStateStore(db_path)
    assert state.seen("101")
    assert state.is_initialized()


def test_legacy_backlog_is_bounded_per_cycle(tmp_path, monkeypatch):
    db_path = tmp_path / "backlog.db"
    plans = [_plan("101"), _plan("102"), _plan("103")]
    processed_ids: list[str] = []

    monkeypatch.setattr(worker, "_refresh_telegram_flow", lambda **kwargs: None)
    monkeypatch.setattr(worker, "refresh_signal_outcomes", lambda **kwargs: [])
    monkeypatch.setattr(worker, "register_recommendations", lambda *args, **kwargs: [])

    # Initialize the durable cursor first, as a normally running production worker would be.
    worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: [],
        interpreter=MockMarketInterpreter(),
    )

    def process(event, **kwargs):
        processed_ids.append(event.event_id)
        return SimpleNamespace(interpretation=object(), recommendations=[])

    monkeypatch.setattr(worker, "process_market_event", process)

    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: list(plans),
        interpreter=MockMarketInterpreter(),
    )

    assert summary.pending == 3
    assert summary.processed == worker.LEGACY_MAX_PER_CYCLE == 1
    assert len(processed_ids) == 1
    state = worker.WorkerStateStore(db_path)
    assert state.seen("103")
    assert not state.seen("101")
    assert not state.seen("102")


def test_outcome_refresh_failure_does_not_fail_cycle(tmp_path, monkeypatch):
    db_path = tmp_path / "outcomes.db"

    monkeypatch.setattr(worker, "_refresh_telegram_flow", lambda **kwargs: None)
    monkeypatch.setattr(
        worker,
        "refresh_signal_outcomes",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("prices unavailable")),
    )

    summary = worker.run_once(
        db_path=db_path,
        plans_fetcher=lambda *args, **kwargs: [],
        interpreter=MockMarketInterpreter(),
    )

    assert summary.outcomes_refreshed == 0
    statuses = {item.step_key: item for item in worker.AnalysisStatusStore(db_path).load()}
    assert statuses["outcome_refresh"].status == "FAILED"
    assert "TimeoutError" in statuses["outcome_refresh"].detail


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
