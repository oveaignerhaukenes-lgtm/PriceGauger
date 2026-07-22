from __future__ import annotations

from telegram_query_builder import build_search_plan
from market_interpreter import MockMarketInterpreter
import worker


def _plan(message_id: str, text: str):
    return build_search_plan(
        message_id=message_id,
        message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
        text=text,
        published_at=f"2026-07-22T20:{int(message_id) % 60:02d}:00+00:00",
    )


def test_worker_bootstraps_latest_then_deduplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "worker.db"
    first = _plan("101", "Iran missile attack on military base")
    second = _plan("102", "Iran drone attack on energy infrastructure")
    plans = [first, second]

    def fetcher(channel, *, minimum_signal):
        assert channel == "Middle_East_Spectator"
        assert minimum_signal == 2
        return list(plans)

    monkeypatch.setattr(worker, "refresh_signal_outcomes", lambda **kwargs: [])

    initial = worker.run_once(
        db_path=db_path,
        plans_fetcher=fetcher,
        interpreter=MockMarketInterpreter(),
    )
    assert initial.fetched == 2
    assert initial.processed == 1
    assert initial.skipped_bootstrap == 1

    repeated = worker.run_once(
        db_path=db_path,
        plans_fetcher=fetcher,
        interpreter=MockMarketInterpreter(),
    )
    assert repeated.pending == 0
    assert repeated.processed == 0

    plans.append(_plan("103", "Iran missile attack on shipping near Hormuz"))
    newest = worker.run_once(
        db_path=db_path,
        plans_fetcher=fetcher,
        interpreter=MockMarketInterpreter(),
    )
    assert newest.pending == 1
    assert newest.processed == 1

    state = worker.WorkerStateStore(db_path)
    assert state.seen("101")
    assert state.seen("102")
    assert state.seen("103")


def test_empty_first_cycle_initializes_without_error(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "refresh_signal_outcomes", lambda **kwargs: [])

    summary = worker.run_once(
        db_path=tmp_path / "empty.db",
        plans_fetcher=lambda *args, **kwargs: [],
        interpreter=MockMarketInterpreter(),
    )

    assert summary.fetched == 0
    assert summary.processed == 0
    assert worker.WorkerStateStore(tmp_path / "empty.db").is_initialized()
