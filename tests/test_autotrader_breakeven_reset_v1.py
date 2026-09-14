from datetime import datetime, timedelta, timezone
from pathlib import Path

from autotrader_breakeven_reset_v1 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    BreakevenResetConfigV1,
    BreakevenResetStateV1,
    REASON_BREAKEVEN_RESET,
    breakeven_reset_due_from_returns_v1,
    evaluate_breakeven_reset_v1,
    reentry_allowed_v1,
)

NOW = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
CONFIG = BreakevenResetConfigV1(cooldown_seconds=60, min_favourable_bps=2.0, breakeven_band_bps=1.0)


def test_fresh_long_does_not_close_before_profit_zone():
    state = BreakevenResetStateV1(100.0, "LONG")
    decision = evaluate_breakeven_reset_v1(state, price=99.99, now=NOW, config=CONFIG)
    assert decision.action == ACTION_HOLD
    assert decision.state.profit_armed is False


def test_long_arms_in_profit_then_closes_on_return_to_entry_band():
    state = BreakevenResetStateV1(100.0, "LONG")
    profitable = evaluate_breakeven_reset_v1(state, price=100.05, now=NOW, config=CONFIG)
    assert profitable.action == ACTION_HOLD
    assert profitable.state.profit_armed is True
    reset = evaluate_breakeven_reset_v1(profitable.state, price=100.005, now=NOW + timedelta(seconds=10), config=CONFIG)
    assert reset.action == ACTION_CLOSE
    assert REASON_BREAKEVEN_RESET in reset.reason
    assert reset.state.cooldown_until == NOW + timedelta(seconds=70)


def test_short_uses_direction_correct_profit_and_breakeven():
    state = BreakevenResetStateV1(100.0, "SHORT")
    profitable = evaluate_breakeven_reset_v1(state, price=99.95, now=NOW, config=CONFIG)
    assert profitable.state.profit_armed is True
    reset = evaluate_breakeven_reset_v1(profitable.state, price=99.995, now=NOW + timedelta(seconds=5), config=CONFIG)
    assert reset.action == ACTION_CLOSE


def test_return_based_runtime_rule_uses_high_water_then_breakeven_band():
    assert breakeven_reset_due_from_returns_v1(
        pnl_pct=-0.01,
        high_water_pct=0.01,
        config=CONFIG,
    ) is False
    assert breakeven_reset_due_from_returns_v1(
        pnl_pct=0.009,
        high_water_pct=0.02,
        config=CONFIG,
    ) is True
    assert breakeven_reset_due_from_returns_v1(
        pnl_pct=-0.20,
        high_water_pct=0.10,
        config=CONFIG,
    ) is True


def test_cooldown_blocks_reentry_for_full_sixty_seconds():
    until = NOW + timedelta(seconds=60)
    assert reentry_allowed_v1(cooldown_until=until, now=NOW + timedelta(seconds=59)) is False
    assert reentry_allowed_v1(cooldown_until=until, now=until) is True


def test_live_close_materializes_global_reset_before_candidate_execution():
    source = Path("autotrader_live_close_v1.py").read_text(encoding="utf-8")
    materialize = source.index("materialize_breakeven_reset_triggers_v1()")
    candidates = source.index("states = _latest_triggered_states()")
    assert materialize < candidates
    assert "REASON_BREAKEVEN_RESET" in source
    assert "_breakeven_currently_executable_v1" in source


def test_entry_policy_blocks_open_during_breakeven_cooldown():
    source = Path("autotrader_entry_policy_v2.py").read_text(encoding="utf-8")
    assert "require_breakeven_reentry_allowed_v1" in source
    assert "pilot_key=enrollment.pilot_key" in source


def test_cooldown_is_product_global_not_strategy_scoped():
    source = Path("autotrader_breakeven_reset_v1.py").read_text(encoding="utf-8")
    function = source[source.index("def latest_breakeven_cooldown_until_v1"):source.index("def require_breakeven_reentry_allowed_v1")]
    assert "event.account_id = ?" in function
    assert "event.uic = ?" in function
    assert "event.asset_type = ?" in function
    assert "rec.pilot_key = ?" not in function


def test_cooldown_starts_at_close_reconciled_flat_not_delayed_pnl_booking():
    source = Path("autotrader_breakeven_reset_v1.py").read_text(encoding="utf-8")
    function = source[source.index("def latest_breakeven_cooldown_until_v1"):source.index("def require_breakeven_reentry_allowed_v1")]
    assert "close.status = 'RECONCILED'" in function
    assert "close.updated_at AS flat_confirmed_at" in function
    assert "pg_v2_autotrader_equity_reconciliations" not in function


def test_autotrader_page_exposes_one_global_control():
    source = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")
    assert "render_breakeven_reset_controls_v1" in source
