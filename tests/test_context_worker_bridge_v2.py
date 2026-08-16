from __future__ import annotations

import inspect
from types import SimpleNamespace

import context_worker_bridge_v2
import telegram_multi_worker


def test_context_bridge_has_no_legacy_technical_llm_composer_or_execution_authority():
    source = inspect.getsource(context_worker_bridge_v2)
    forbidden = (
        "state_runtime_pipeline",
        "process_flow_snapshot",
        "technical_core",
        "OpenAI",
        "openai",
        "Holistic",
        "place_order",
        "AutoTrader",
    )
    for token in forbidden:
        assert token not in source


def test_multi_worker_publishes_context_v2_after_existing_cycle(monkeypatch, tmp_path):
    events: list[str] = []
    expected = SimpleNamespace(name="worker-result")
    snapshot = SimpleNamespace(
        snapshot_id="context-1",
        freshness_status="FRESH",
    )

    class FakeChannelStore:
        def __init__(self, _path):
            pass

        def list_enabled(self):
            return []

    def fake_worker_run_once(**_kwargs):
        events.append("worker")
        return expected

    def fake_publish_latest_context_v2(**_kwargs):
        events.append("context_v2")
        return snapshot, True

    monkeypatch.setattr(telegram_multi_worker, "TelegramChannelStore", FakeChannelStore)
    monkeypatch.setattr(telegram_multi_worker.worker_module, "run_once", fake_worker_run_once)
    monkeypatch.setattr(
        telegram_multi_worker,
        "publish_latest_context_v2",
        fake_publish_latest_context_v2,
    )

    result = telegram_multi_worker.run_once(db_path=tmp_path / "context.db")

    assert result is expected
    assert events == ["worker", "context_v2"]


def test_context_v2_publication_failure_does_not_erase_existing_cycle(monkeypatch, tmp_path):
    expected = SimpleNamespace(name="worker-result")

    class FakeChannelStore:
        def __init__(self, _path):
            pass

        def list_enabled(self):
            return []

    monkeypatch.setattr(telegram_multi_worker, "TelegramChannelStore", FakeChannelStore)
    monkeypatch.setattr(
        telegram_multi_worker.worker_module,
        "run_once",
        lambda **_kwargs: expected,
    )

    def fail_publish(**_kwargs):
        raise RuntimeError("context v2 unavailable")

    monkeypatch.setattr(telegram_multi_worker, "publish_latest_context_v2", fail_publish)

    assert telegram_multi_worker.run_once(db_path=tmp_path / "context.db") is expected
