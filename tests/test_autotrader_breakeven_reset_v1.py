from datetime import datetime, timedelta, timezone

from autotrader_breakeven_reset_v1 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    BreakevenResetConfigV1,
    BreakevenResetStateV1,
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
    assert reset.state.cooldown_until == NOW + timedelta(seconds=70)


def test_short_uses_direction_correct_profit_and_breakeven():
    state = BreakevenResetStateV1(100.0, "SHORT")
    profitable = evaluate_breakeven_reset_v1(state, price=99.95, now=NOW, config=CONFIG)
    assert profitable.state.profit_armed is True
    reset = evaluate_breakeven_reset_v1(profitable.state, price=99.995, now=NOW + timedelta(seconds=5), config=CONFIG)
    assert reset.action == ACTION_CLOSE


def test_cooldown_blocks_reentry_for_full_sixty_seconds():
    until = NOW + timedelta(seconds=60)
    assert reentry_allowed_v1(cooldown_until=until, now=NOW + timedelta(seconds=59)) is False
    assert reentry_allowed_v1(cooldown_until=until, now=until) is True
