from __future__ import annotations

import inspect

import worker


def test_worker_no_longer_imports_or_calls_legacy_semantic_runtime() -> None:
    source = inspect.getsource(worker)
    assert "state_runtime_pipeline" not in source
    assert "process_flow_snapshot" not in source


def test_telegram_flow_refresh_does_not_write_retired_semantic_statuses() -> None:
    source = inspect.getsource(worker._refresh_telegram_flow)
    for retired_step in (
        '"information_state"',
        '"technical_state"',
        '"decision_state"',
        '"recommendation"',
    ):
        assert retired_step not in source
