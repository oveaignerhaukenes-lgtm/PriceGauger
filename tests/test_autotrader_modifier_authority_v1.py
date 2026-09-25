from unittest.mock import patch

import autotrader_breakeven_reset_v1 as breakeven
import autotrader_live_close_v1 as close
import autotrader_take_profit_modifier_v1 as take_profit


def test_disabled_breakeven_does_not_create_live_exit():
    with patch.object(breakeven, "using_postgres", return_value=True), patch(
        "autotrader_modifier_authority_v1.modifier_enabled_v1", return_value=False
    ), patch.object(breakeven, "ensure_breakeven_reset_schema_v1", side_effect=AssertionError("exit created")):
        assert breakeven.materialize_breakeven_reset_triggers_v1() == 0


def test_disabled_take_profit_does_not_create_target():
    with patch.object(take_profit, "using_postgres", return_value=True), patch(
        "autotrader_modifier_authority_v1.modifier_enabled_v1", return_value=False
    ), patch.object(take_profit, "ensure_take_profit_schema_v1", side_effect=AssertionError("target created")):
        assert take_profit.run_take_profit_observations_v1(()).requests_created == 0


def test_disabled_exit_authority_blocks_pending_guardian_trigger():
    state = {"account_id": "a", "net_position_id": "p", "triggered_reason": "HARD_STOP"}
    with patch.object(close, "load_live_close_config_v1", return_value=close.LiveCloseConfigV1(True)), patch.object(
        close, "code_gate_enabled_v1", return_value=True
    ), patch.object(close, "modifier_enabled_v1", return_value=False), patch.object(
        close, "_latest_triggered_states", return_value=[state]
    ), patch.object(close, "_has_pending_reconciliation_v1", return_value=False), patch.object(
        close, "_require_live_client", return_value=object()
    ), patch.object(close, "_position_netting_mode", return_value="Intraday"), patch.object(
        close, "_reconcile_accepted_attempts", return_value=0
    ), patch.object(close, "load_risk_config_v2"), patch.object(
        close, "_latest_event_id", return_value="event"
    ), patch.object(close, "_attempt_status", return_value=None), patch.object(
        close, "_current_observation", return_value=object()
    ), patch.object(close, "is_position_managed_v1", return_value=True), patch.object(
        close, "_same_trigger_basis", return_value=True
    ), patch.object(close, "_post_once", side_effect=AssertionError("broker order submitted")):
        summary = close.run_live_close_cycle_v1()
        assert summary.submitted == 0
        assert summary.blocked == 1
