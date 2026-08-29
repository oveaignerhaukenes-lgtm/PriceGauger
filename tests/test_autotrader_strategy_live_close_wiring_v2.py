from pathlib import Path


def test_strategy_close_reuses_hardened_live_close_boundaries():
    source = Path("autotrader_strategy_live_close_v2.py").read_text(encoding="utf-8")
    assert "code_gate_enabled_v1" in source
    assert "load_live_close_config_v1" in source
    assert "_require_live_client" in source
    assert "_position_netting_mode" in source
    assert "is_position_managed_v1" in source
    assert "_precheck_is_clear" in source
    assert "_record_attempt_before_submit" in source
    assert "_post_once(client, \"trade/v2/orders\", payload)" in source
    assert "blind retry blocked" in source


def test_strategy_runtime_persists_requests_before_execution_and_worker_runs_both_layers():
    runtime = Path("autotrader_automanage_runtime_v2.py").read_text(encoding="utf-8")
    worker = Path("realtime_worker.py").read_text(encoding="utf-8")
    schema = Path("autotrader_schema_v2.py").read_text(encoding="utf-8")

    assert "pg_v2_autotrader_execution_requests" in runtime
    assert "ON CONFLICT (request_id) DO NOTHING" in runtime
    assert "run_automanage_strategy_forever_v2" in worker
    assert "run_strategy_live_close_forever_v2" in worker
    for table in (
        "pg_v2_autotrader_strategy_runtime_state",
        "pg_v2_autotrader_strategy_evaluations",
        "pg_v2_autotrader_execution_requests",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema
