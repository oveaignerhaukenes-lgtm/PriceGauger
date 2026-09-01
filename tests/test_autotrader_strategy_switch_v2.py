from __future__ import annotations

from pathlib import Path


def test_strategy_switch_is_control_plane_only_and_keeps_stable_pilot_identity() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert "UPDATE pg_v2_autotrader_strategy_enrollments" in source
    assert "SET strategy_key = ?, live_open_armed = FALSE" in source
    assert "UPDATE pg_v2_autotrader_execution_requests" in source
    assert "status = 'SUPERSEDED'" in source
    assert "block_reason = 'STRATEGY_SWITCH'" in source
    assert "DELETE FROM pg_v2_autotrader_live_pilot_state" in source
    assert "DELETE FROM pg_v2_autotrader_mtf_live_state" in source
    assert "pg_v2_autotrader_strategy_switch_events" in source
    assert "INSERT INTO pg_v2_autotrader_strategy_enrollments" not in source
    assert "_post_once" not in source
    assert "trade/v2/orders" not in source


def test_strategy_switch_refuses_target_that_cannot_adopt_current_exposure() -> None:
    source = Path("autotrader_strategy_switch_v2.py").read_text(encoding="utf-8")
    assert 'observed_direction == "LONG" and not target.can_long' in source
    assert 'observed_direction == "SHORT" and not target.can_short' in source
    assert "target strategy cannot adopt the currently observed LONG exposure" in source
    assert "target strategy cannot adopt the currently observed SHORT exposure" in source


def test_entry_gate_exposes_explicit_strategy_switch_and_disarms_open() -> None:
    source = Path("tradingdesk_autotrade_entry_gate_v2.py").read_text(encoding="utf-8")
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "switch_live_strategy_v2" in source
    assert '"Bytt LIVE-strategi"' in source
    assert "Selve byttet sender ingen ordre" in source
    assert "LIVE OPEN/re-entry blir disarmed" in source
    assert "st.rerun()" in source
