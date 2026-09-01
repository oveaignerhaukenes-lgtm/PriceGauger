from __future__ import annotations

from pathlib import Path


def test_strategy_switch_is_control_plane_only_and_creates_clean_target_pilot() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "enrollment.product.pilot_key(target.key)" in source
    assert "strategy switch requires confirmed FLAT exposure" in source
    assert "target strategy pilot already has history" in source
    assert "initialize_pilot_equity_v2" in source
    assert "save_pilot_margin_config_v2" in source
    assert "UPDATE pg_v2_autotrader_strategy_enrollments" in source
    assert "SET enabled = FALSE, live_open_armed = FALSE" in source
    assert "INSERT INTO pg_v2_autotrader_strategy_enrollments" in source
    assert "TRUE, FALSE" in source
    assert "UPDATE pg_v2_autotrader_execution_requests" in source
    assert "status = 'SUPERSEDED'" in source
    assert "block_reason = 'STRATEGY_SWITCH'" in source
    assert "DELETE FROM pg_v2_autotrader_strategy_runtime_state" in source
    assert "DELETE FROM pg_v2_autotrader_live_pilot_state" in source
    assert "DELETE FROM pg_v2_autotrader_mtf_live_state" in source
    assert "pg_v2_autotrader_strategy_switch_events" in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source


def test_strategy_switch_never_adopts_open_exposure_between_strategy_cohorts() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "_confirmed_flat_v2(enrollment)" in source
    assert "currently observed {observed}" in source
    assert 'observed_direction="FLAT"' in source


def test_entry_gate_exposes_explicit_strategy_switch_and_disarms_open() -> None:
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert '"Bytt LIVE-strategi"' in source
    assert "Selve byttet sender ingen ordre" in source
    assert "LIVE OPEN/re-entry blir disarmed" in source
    assert "st.rerun()" in source
