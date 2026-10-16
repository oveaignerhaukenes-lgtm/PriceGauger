"""Fraktal#1: deterministic multi-scale rhythm decisions; NO broker authority.

V3 strategy: only fully-closed canonical 1-minute closes, three independently
confirmed reversal scales, one Saxo-legal tranche, conservative flat-first exits.
The output is an INVENTORY TARGET, never a direct broker order. This policy has
no claim of positive expected return and is unarmed unless deliberately selected
and authorized through existing V3 LIVE controls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

import pandas as pd

from autotrader_market_rhythm_v1 import ConfirmedTurnV1, confirmed_turns_v1

STRATEGY_KEY_V3 = "fraktal-1-v1"
MINUTE = timedelta(minutes=1)
REVERSION_THRESHOLDS_PCT = (0.05, 0.15, 0.35)
# For a new entry all three *confirmed* swing directions must agree.
CONTEXT_MAX_AGE_MINUTES = (8, 60, 240)
ENTRY_COOLDOWN_MINUTES = 4
MAX_INPUT_BARS = 2500


@dataclass(frozen=True)
class FraktalStateV1:
    last_bar_end: datetime
    target_amount: float
    last_open_bar_end: datetime | None = None

    def __post_init__(self):
        if not isfinite(self.target_amount):
            raise ValueError("Nonfinite target amount")
        if self.last_bar_end.tzinfo is None:
            raise ValueError("last bar end requires timezone")


@dataclass(frozen=True)
class FraktalDecisionV1:
    state: FraktalStateV1
    action: str
    reason: str


def _utc(value) -> datetime:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("Invalid candle timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").to_pydatetime()


def causal_closes_v1(source_bars: Sequence, *, now: datetime) -> pd.Series:
    """Only candles with the 1-minute window fully closed + 10 seconds."""
    clock = _utc(now)
    pairs: list[tuple[datetime, float]] = []
    for bar in source_bars[-MAX_INPUT_BARS:]:
        stamp = _utc(bar.bar_time)
        end = stamp + MINUTE
        value = float(bar.close)
        if not isfinite(value) or value <= 0:
            continue
        if end + timedelta(seconds=10) > clock:
            continue
        pairs.append((end, value))
    if not pairs:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    pairs.sort(key=lambda x: x[0])
    if len({p[0] for p in pairs}) != len(pairs):
        # Malformed/duplicate provider timeline: cannot prove distinct bars.
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    return pd.Series(
        [p[1] for p in pairs],
        index=pd.DatetimeIndex([p[0] for p in pairs], tz="UTC"),
        dtype=float,
    )


def _last_causal_turn(turns: tuple[ConfirmedTurnV1, ...], end: datetime):
    return next((x for x in reversed(turns) if _utc(x.confirmed_at) <= end), None)


def _turn_direction(turn: ConfirmedTurnV1 | None):
    return (1 if turn is not None and turn.kind == "TROUGH"
            else -1 if turn is not None and turn.kind == "PEAK" else 0)


def fractal_step_v1(
    state: FraktalStateV1, *, prices: pd.Series, tranche: float,
) -> FraktalDecisionV1:
    """Process exactly one *new*, contiguous closed bar, no replay entry.

    Fresh micro-turn plus meso+macro agreement authorizes one-unit entry.
    Opposing micro/meso/macro turn closes the old leg first; no direct flip.
    Any gap/incomplete scale freezes new exposure. A vetoed/external target
    is reconciled to actual broker quantity by the V3 adapter before decisions.
    """
    if not isfinite(tranche) or tranche <= 0:
        raise ValueError("Invalid legal Saxo tranche")
    if prices.empty:
        return FraktalDecisionV1(state, "HOLD_NO_DATA", "No canonical closed bars")
    end = _utc(prices.index[-1])
    if end <= _utc(state.last_bar_end):
        return FraktalDecisionV1(state, "HOLD_DUPLICATE", "Already processed")
    advanced = FraktalStateV1(end, state.target_amount, state.last_open_bar_end)
    if end - _utc(state.last_bar_end) != MINUTE:
        return FraktalDecisionV1(advanced, "HOLD_MISSING_1M", "Missing completed 1m cadence")

    # Freshness and scale consistency: all pivots are known only at their
    # confirmation timestamp, not the earlier extreme.
    turns = tuple(
        confirmed_turns_v1(prices, reversal_pct=threshold)
        for threshold in REVERSION_THRESHOLDS_PCT
    )
    # If the market was closed / a canonical minute was missing, a turn from
    # before the gap must not be treated as an active confirmation now.
    gaps = pd.Series(prices.index, index=prices.index).diff()
    segment_start = (
        gaps[gaps > pd.Timedelta(minutes=1)].index[-1]
        if (gaps > pd.Timedelta(minutes=1)).any() else prices.index[0]
    )
    latest = tuple(
        next((ev for ev in reversed(scale)
              if _utc(ev.confirmed_at) <= end
              and _utc(ev.confirmed_at) >= _utc(segment_start)), None)
        for scale in turns
    )
    directions = tuple(_turn_direction(t) for t in latest)
    current = float(state.target_amount)
    side = 1 if current > 0 else -1 if current < 0 else 0
    if abs(current) > tranche + 1e-9:
        # Never compound; outside oversized Saxo positions are not promoted.
        # Safety reduces are handled by the ordinary V3 risk/account owner.
        return FraktalDecisionV1(advanced, "HOLD_OVERSIZED", "Existing inventory exceeds one legal tranche")

    # A newly CONFIRMED change of direction is a reason to leave the old
    # position. Waiting to enter the opposite side requires a later signal.
    contrary_fresh = any(
        turn is not None and _utc(turn.confirmed_at) == end
        and direction == -side
        for turn, direction in zip(latest, directions)
    )
    if side and contrary_fresh:
        return FraktalDecisionV1(
            FraktalStateV1(end, 0.0, state.last_open_bar_end),
            "CONFIRMED_OPPOSITE_FLAT", "New confirmed counter-swing; CLOSE to verified FLAT",
        )

    if side:
        return FraktalDecisionV1(advanced, "HOLD_POSITION", "One-unit position; no scale-up")
    if not all(directions) or len(set(directions)) != 1:
        return FraktalDecisionV1(advanced, "HOLD_SCALE_CONFLICT", "Confirmed scales do not agree")
    micro = latest[0]
    if micro is None or _utc(micro.confirmed_at) != end:
        return FraktalDecisionV1(advanced, "HOLD_NO_FRESH_ENTRY", "No new confirmed micro-turn")
    if any(
        turn is None or (end - _utc(turn.confirmed_at)) > timedelta(minutes=age)
        for turn, age in zip(latest, CONTEXT_MAX_AGE_MINUTES)
    ):
        return FraktalDecisionV1(advanced, "HOLD_STALE_SCALE", "Higher-scale confirmation too old")
    if (state.last_open_bar_end is not None
            and end - _utc(state.last_open_bar_end) < timedelta(minutes=ENTRY_COOLDOWN_MINUTES)):
        return FraktalDecisionV1(advanced, "HOLD_COOLDOWN", "Entry cooldown")

    one = float(tranche) * directions[0]
    return FraktalDecisionV1(
        FraktalStateV1(end, one, end),
        "FRACTAL_LONG" if one > 0 else "FRACTAL_SHORT",
        "Fresh micro reversal + confirmed meso/macro agreement; exactly one legal Saxo unit",
    )


__all__ = [
    "STRATEGY_KEY_V3", "FraktalStateV1", "FraktalDecisionV1",
    "REVERSION_THRESHOLDS_PCT", "causal_closes_v1", "fractal_step_v1",
]
