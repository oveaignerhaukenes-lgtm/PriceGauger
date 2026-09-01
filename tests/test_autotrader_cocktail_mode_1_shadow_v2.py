from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from autotrader_cocktail_mode_1_shadow_v2 import (
    ACTION_FLAT,
    ACTION_FLIP_LONG,
    ACTION_FLIP_SHORT,
    ACTION_HOLD,
    ACTION_OPEN_LONG,
    ACTION_OPEN_SHORT,
    CROSS_DOWN,
    CROSS_UP,
    MODE_NORMAL,
    MODE_SHOCK,
    MODE_TREND_LOCK,
    MODE_WHIPSAW,
    POSITION_FLAT,
    POSITION_LONG,
    POSITION_SHORT,
    CocktailSnapshotV1,
    CocktailStateV1,
    MacdClockV1,
    apply_cocktail_decision_v1,
    cocktail_mode_1_decision_v1,
)


NOW = datetime(2026, 9, 2, 0, 1, tzinfo=timezone.utc)


def _clock(tf: int, *, spread: float, cross: str | None = None, velocity: float = 0.0) -> MacdClockV1:
    return MacdClockV1(
        timeframe_minutes=tf,
        macd=spread,
        signal=0.0,
        spread=spread,
        previous_spread=-0.1 if cross == CROSS_UP else (0.1 if cross == CROSS_DOWN else spread * 0.9),
        previous2_spread=spread * 0.8,
        velocity_atr=velocity,
        acceleration_atr=0.0,
        cross=cross,
        cross_observed_at=NOW if cross else None,
        cross_estimated_at=NOW if cross else None,
    )


def _snapshot(
    *,
    c5: str | None = None,
    c10: str | None = None,
    c15: str | None = None,
    c30: str | None = None,
    shock: str | None = None,
    trend: str | None = None,
    whipsaw: bool = False,
    escape: str | None = None,
    low_activity: bool = False,
    divergent: bool = False,
    data_gap: bool = False,
) -> CocktailSnapshotV1:
    return CocktailSnapshotV1(
        action_at=NOW,
        market_id=1,
        instrument_id=7,
        market_name="US Tech 100 NAS · Saxo 4912",
        price=100.0,
        clock_5m=_clock(5, spread=1.0 if c5 == CROSS_UP else -1.0 if c5 == CROSS_DOWN else 0.5, cross=c5),
        clock_10m=_clock(10, spread=1.0 if c10 == CROSS_UP else -1.0 if c10 == CROSS_DOWN else 0.4, cross=c10),
        clock_15m=_clock(15, spread=1.0 if c15 == CROSS_UP else -1.0 if c15 == CROSS_DOWN else 0.3, cross=c15),
        clock_30m=_clock(30, spread=1.0 if c30 == CROSS_UP else -1.0 if c30 == CROSS_DOWN else 0.2, cross=c30),
        atr_5m=10.0,
        atr_10m=20.0,
        atr_30m=50.0,
        range_ratio_1m=1.0,
        activity_z=0.0,
        activity_source="range_proxy",
        efficiency_5m=0.5,
        efficiency_30m=0.5,
        displacement_5m_atr5=0.2,
        displacement_30m_atr10=0.5,
        support=90.0,
        resistance=110.0,
        break_direction=None,
        break_distance_atr5=0.0,
        low_activity=low_activity,
        divergent_5_10=divergent,
        shock_direction=shock,
        trend_lock_direction=trend,
        whipsaw=whipsaw,
        escape_direction=escape,
        recent_fast_crosses_30m=3 if whipsaw else 0,
        data_gap=data_gap,
    )


def _state(position: str, *, mode: str = MODE_NORMAL, pending: str | None = None, tf: int | None = None) -> CocktailStateV1:
    return CocktailStateV1(
        instrument_id=7,
        market_id=1,
        market_name="US Tech 100 NAS · Saxo 4912",
        position=position,
        mode=mode,
        pending_direction=pending,
        pending_confirmation_tf=tf,
        entry_price=None if position == POSITION_FLAT else 100.0,
    )


def test_normal_counter_5m_cross_flattens_before_opposite_entry() -> None:
    decision = cocktail_mode_1_decision_v1(_state(POSITION_LONG), _snapshot(c5=CROSS_DOWN))
    assert decision.action == ACTION_FLAT
    assert decision.target_position == POSITION_FLAT
    assert decision.pending_direction == POSITION_SHORT
    assert decision.pending_confirmation_tf == 10


def test_pending_normal_flip_waits_for_10m_cross_confirmation() -> None:
    state = _state(POSITION_FLAT, pending=POSITION_SHORT, tf=10)
    waiting = cocktail_mode_1_decision_v1(state, _snapshot())
    assert waiting.action == ACTION_HOLD
    assert waiting.pending_direction == POSITION_SHORT

    confirmed = cocktail_mode_1_decision_v1(state, _snapshot(c10=CROSS_DOWN))
    assert confirmed.action == ACTION_OPEN_SHORT
    assert confirmed.target_position == POSITION_SHORT
    assert confirmed.pending_direction is None


def test_shock_can_override_slow_trend_and_flip_fast() -> None:
    decision = cocktail_mode_1_decision_v1(
        _state(POSITION_LONG, mode=MODE_TREND_LOCK),
        _snapshot(shock=POSITION_SHORT, trend=POSITION_LONG),
    )
    assert decision.action == ACTION_FLIP_SHORT
    assert decision.target_position == POSITION_SHORT
    assert decision.mode == MODE_SHOCK


def test_trend_lock_ignores_5m_counter_noise_but_10m_exits_and_15m_confirms() -> None:
    locked = _state(POSITION_SHORT)
    ignored = cocktail_mode_1_decision_v1(
        locked,
        _snapshot(c5=CROSS_UP, trend=POSITION_SHORT),
    )
    assert ignored.action == ACTION_HOLD
    assert ignored.target_position == POSITION_SHORT
    assert ignored.mode == MODE_TREND_LOCK

    exit_decision = cocktail_mode_1_decision_v1(
        locked,
        _snapshot(c10=CROSS_UP, trend=POSITION_SHORT),
    )
    assert exit_decision.action == ACTION_FLAT
    assert exit_decision.pending_direction == POSITION_LONG
    assert exit_decision.pending_confirmation_tf == 15

    pending = _state(POSITION_FLAT, mode=MODE_TREND_LOCK, pending=POSITION_LONG, tf=15)
    entry = cocktail_mode_1_decision_v1(pending, _snapshot(c15=CROSS_UP))
    assert entry.action == ACTION_OPEN_LONG
    assert entry.target_position == POSITION_LONG


def test_whipsaw_is_an_explicit_flat_state_until_escape_threshold() -> None:
    enter = cocktail_mode_1_decision_v1(_state(POSITION_LONG), _snapshot(whipsaw=True))
    assert enter.action == ACTION_FLAT
    assert enter.mode == MODE_WHIPSAW

    paused = cocktail_mode_1_decision_v1(_state(POSITION_FLAT, mode=MODE_WHIPSAW), _snapshot())
    assert paused.action == ACTION_HOLD
    assert paused.target_position == POSITION_FLAT
    assert paused.mode == MODE_WHIPSAW

    escaped = cocktail_mode_1_decision_v1(
        _state(POSITION_FLAT, mode=MODE_WHIPSAW),
        _snapshot(escape=POSITION_LONG),
    )
    assert escaped.action == ACTION_OPEN_LONG
    assert escaped.target_position == POSITION_LONG


def test_low_activity_5m_10m_divergence_pauses_flat() -> None:
    decision = cocktail_mode_1_decision_v1(
        _state(POSITION_SHORT),
        _snapshot(low_activity=True, divergent=True),
    )
    assert decision.action == ACTION_FLAT
    assert decision.target_position == POSITION_FLAT


def test_data_gap_never_infers_cross_and_flattens_exposure() -> None:
    decision = cocktail_mode_1_decision_v1(
        _state(POSITION_LONG),
        _snapshot(c30=CROSS_DOWN, data_gap=True),
    )
    assert decision.action == ACTION_FLAT
    assert decision.target_position == POSITION_FLAT
    assert "DATA_GAP_PAUSE" in decision.reason


def test_shadow_transition_accounts_long_and_short_gross_returns() -> None:
    long_state = _state(POSITION_LONG)
    exit_snapshot = _snapshot()
    exit_snapshot = CocktailSnapshotV1(**{**{name: getattr(exit_snapshot, name) for name in exit_snapshot.__dataclass_fields__}, "price": 110.0})
    flat_decision = cocktail_mode_1_decision_v1(long_state, _snapshot(c5=CROSS_DOWN))
    updated = apply_cocktail_decision_v1(long_state, exit_snapshot, flat_decision)
    assert round(updated.realized_return_pct, 6) == 10.0

    short_state = CocktailStateV1(
        instrument_id=7,
        market_id=1,
        market_name="x",
        position=POSITION_SHORT,
        entry_price=100.0,
    )
    short_exit = CocktailSnapshotV1(**{**{name: getattr(exit_snapshot, name) for name in exit_snapshot.__dataclass_fields__}, "price": 90.0})
    decision = type(flat_decision)(ACTION_FLAT, POSITION_FLAT, MODE_NORMAL, None, None, "test")
    updated_short = apply_cocktail_decision_v1(short_state, short_exit, decision)
    assert round(updated_short.realized_return_pct, 6) == 10.0


def test_cocktail_shadow_has_no_execution_or_saxo_post_authority() -> None:
    source = Path("autotrader_cocktail_mode_1_shadow_v2.py").read_text(encoding="utf-8")
    assert "trade/v2/orders" not in source
    assert "_post_once" not in source
    assert "pg_v2_autotrader_execution_requests" not in source
    assert "live_open" not in source
    assert "live_close" not in source
    assert "BOOTSTRAP_NO_REPLAY" in source
    assert "CANONICAL_1M_INTRABAR_MACD" in source
