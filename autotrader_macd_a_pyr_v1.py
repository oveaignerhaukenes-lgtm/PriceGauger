"""MACD-A pyramiding signal planner (shadow-only; no broker side effects).

MACD-A owns direction. Each fresh, *closed-bar* MACD cross on an enabled
timeframe in that direction earns one 0.02 tranche, up to a configured cap.
Reversal always emits CLOSE; reopening requires a later confirmed FLAT state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Mapping

STRATEGY_KEY = "macd-a-pyr-v1"
DEFAULT_TIMEFRAMES = (1, 2, 5)
LONG, SHORT, FLAT = "LONG", "SHORT", "FLAT"


@dataclass(frozen=True)
class Cross:
    timeframe_minutes: int
    closed_at: datetime
    previous_spread: float
    current_spread: float

    def __post_init__(self) -> None:
        if self.timeframe_minutes <= 0 or self.closed_at.tzinfo is None:
            raise ValueError("cross requires positive timeframe and timezone-aware close")
        if not isfinite(self.previous_spread) or not isfinite(self.current_spread):
            raise ValueError("MACD spread must be finite")

    @property
    def direction(self) -> str:
        if self.previous_spread <= 0 < self.current_spread:
            return LONG
        if self.previous_spread >= 0 > self.current_spread:
            return SHORT
        return FLAT

    @property
    def event_id(self) -> str:
        return f"{self.timeframe_minutes}m:{self.closed_at.isoformat()}:{self.direction}"


@dataclass(frozen=True)
class PyramidState:
    direction: str = FLAT
    tranches: int = 0
    seen_events: frozenset[str] = frozenset()
    pending_flat: bool = False


@dataclass(frozen=True)
class PyramidDecision:
    action: str
    direction: str
    amount: float
    target_amount: float
    state: PyramidState
    reason: str


def plan_macd_a_pyramid(
    *,
    state: PyramidState,
    macd_a_direction: str,
    observed_direction: str,
    crosses: tuple[Cross, ...],
    tranche_amount: float = 0.02,
    max_amount: float = 0.20,
    enabled_timeframes: tuple[int, ...] = DEFAULT_TIMEFRAMES,
) -> PyramidDecision:
    """Plan one bounded action, never submit an order.

    The caller must persist state and reconcile broker fills before advancing
    observed_direction. On any opposite MACD-A direction, CLOSE is the only
    permitted action until the caller observes FLAT.
    """
    if any(x not in (LONG, SHORT, FLAT) for x in (macd_a_direction, observed_direction, state.direction)):
        raise ValueError("invalid direction")
    if not (isfinite(tranche_amount) and isfinite(max_amount) and tranche_amount > 0 and max_amount >= tranche_amount):
        raise ValueError("invalid tranche or cap")
    if state.tranches < 0 or state.tranches * tranche_amount > max_amount + 1e-9:
        raise ValueError("invalid existing inventory")
    if len(set(enabled_timeframes)) != len(enabled_timeframes) or any(x <= 0 for x in enabled_timeframes):
        raise ValueError("invalid timeframes")
    def result(action: str, direction: str, amount: float, next_state: PyramidState, reason: str) -> PyramidDecision:
        return PyramidDecision(action, direction, amount, next_state.tranches * tranche_amount, next_state, reason)

    if state.pending_flat:
        if observed_direction != FLAT:
            return result("CLOSE", FLAT, 0.0, state, "await confirmed flat")
        state = PyramidState(seen_events=state.seen_events)
    if macd_a_direction == FLAT or (state.direction != FLAT and macd_a_direction != state.direction):
        next_state = PyramidState(seen_events=state.seen_events, pending_flat=observed_direction != FLAT)
        return result("CLOSE" if observed_direction != FLAT else "HOLD", FLAT, 0.0, next_state, "MACD-A exit/reversal")
    if observed_direction not in (FLAT, macd_a_direction):
        return result("CLOSE", FLAT, 0.0, PyramidState(seen_events=state.seen_events, pending_flat=True), "opposite observed exposure")
    if state.direction != FLAT and observed_direction == FLAT:
        # Never re-create a position after an external/manual flat.
        return result("HOLD", FLAT, 0.0, PyramidState(seen_events=state.seen_events), "external flat requires fresh signal")
    ordered = sorted(crosses, key=lambda c: (c.closed_at, c.timeframe_minutes))
    eligible = [c for c in ordered if c.timeframe_minutes in enabled_timeframes and c.direction == macd_a_direction and c.event_id not in state.seen_events]
    # Consume every delivered event, including opposite/duplicate crosses.
    seen = state.seen_events | frozenset(c.event_id for c in crosses)
    if not eligible:
        next_state = PyramidState(state.direction, state.tranches, seen)
        return result("HOLD", state.direction, 0.0, next_state, "no fresh aligned cross")
    capacity = int((max_amount + 1e-9) / tranche_amount)
    available = max(0, capacity - state.tranches)
    if available == 0:
        return result("HOLD", state.direction, 0.0, PyramidState(state.direction, state.tranches, seen), "exposure cap")
    # One order per evaluation; remaining simultaneous crosses must be replayed
    # by the durable event queue after the first fill is reconciled.
    selected = eligible[0]
    seen = state.seen_events | frozenset(c.event_id for c in crosses if c.event_id != selected.event_id)
    seen = seen | {selected.event_id}
    next_state = PyramidState(macd_a_direction, state.tranches + 1, frozenset(seen))
    return result("OPEN" if state.tranches == 0 else "ADD", macd_a_direction, tranche_amount, next_state, selected.event_id)
