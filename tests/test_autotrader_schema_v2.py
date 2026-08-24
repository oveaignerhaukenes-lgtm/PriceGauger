from __future__ import annotations

from pathlib import Path

from autotrader_risk_control_v2 import RiskConfigV2
from autotrader_schema_v2 import DEFAULT_HARD_STOP_PCT


def test_canonical_default_hard_stop_is_minus_two_percent() -> None:
    assert DEFAULT_HARD_STOP_PCT == -2.0
    assert RiskConfigV2().hard_stop_pct == DEFAULT_HARD_STOP_PCT


def test_schema_owns_all_active_autotrader_tables() -> None:
    source = Path("autotrader_schema_v2.py").read_text(encoding="utf-8")
    for table in (
        "pg_v2_autotrader_risk_config",
        "pg_v2_autotrader_risk_state",
        "pg_v2_autotrader_risk_events",
        "pg_v2_autotrader_managed_positions",
        "pg_v2_autotrader_live_close_config",
        "pg_v2_autotrader_live_close_attempts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source


def test_runtime_modules_and_ui_do_not_own_ddl() -> None:
    for path in (
        "autotrader_risk_control_v2.py",
        "autotrader_managed_positions_v1.py",
        "autotrader_live_close_v1.py",
        "autotrader_risk_control_ui_v2.py",
        "autotrader_live_close_ui_v1.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "CREATE TABLE" not in source

    risk_ui = Path("autotrader_risk_control_ui_v2.py").read_text(encoding="utf-8")
    live_ui = Path("autotrader_live_close_ui_v1.py").read_text(encoding="utf-8")
    assert "ensure_autotrader_schema_v2" not in risk_ui
    assert "ensure_autotrader_schema_v2" not in live_ui


def test_existing_config_is_not_overwritten_by_new_default() -> None:
    source = Path("autotrader_schema_v2.py").read_text(encoding="utf-8")
    assert "VALUES (1, TRUE, -2.0" in source
    assert "ON CONFLICT (config_id) DO NOTHING" in source
