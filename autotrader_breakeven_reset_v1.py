from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal


DirectionV1 = Literal["LONG", "SHORT"]
ACTION_HOLD = "HOLD"
ACTION_CLOSE = "CLOSE"
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_MIN_FAVOURABLE_BPS = 2.0
DEFAULT_BREAKEVEN_BAND_BPS = 1.0


@dataclass(frozen=True, slots=True)
class BreakevenResetConfigV1:
    enabled: bool = True
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    min_favourable_bps: float = DEFAULT_MIN_FAVOURABLE_BPS
    breakeven_band_bps: float = DEFAULT_BREAKEVEN_BAND_BPS


@dataclass(frozen=True, slots=True)
class BreakevenResetStateV1:
    entry_price: float
    direction: DirectionV1
    profit_armed: bool = False
    favourable_extreme: float | None = None
    cooldown_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class BreakevenResetDecisionV1:
    action: str
    state: BreakevenResetStateV1
    reason: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _bps(entry: float, price: float, direction: DirectionV1) -> float:
    if entry <= 0.0:
        raise ValueError("entry_price must be positive")
    raw = (float(price) - float(entry)) / float(entry) * 10000.0
    return raw if direction == "LONG" else -raw


def evaluate_breakeven_reset_v1(
    state: BreakevenResetStateV1,
    *,
    price: float,
    now: datetime,
    config: BreakevenResetConfigV1 = BreakevenResetConfigV1(),
) -> BreakevenResetDecisionV1:
    """Global AutoManage policy: bank a round trip to breakeven, then reassess.

    The guard only arms after the position has first travelled favourably by the
    configured amount. It therefore cannot close a fresh entry merely because spread
    places the first quote around entry. Once armed, a return into/beyond the
    breakeven band requests CLOSE. Re-entry authority is intentionally separate.
    """
    now = _utc(now)
    if not config.enabled:
        return BreakevenResetDecisionV1(ACTION_HOLD, state, "disabled")
    if state.direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if price <= 0.0:
        raise ValueError("price must be positive")

    favourable = _bps(state.entry_price, price, state.direction)
    extreme = favourable if state.favourable_extreme is None else max(state.favourable_extreme, favourable)
    armed = bool(state.profit_armed or extreme >= max(0.0, float(config.min_favourable_bps)))
    updated = BreakevenResetStateV1(
        entry_price=state.entry_price,
        direction=state.direction,
        profit_armed=armed,
        favourable_extreme=extreme,
        cooldown_until=state.cooldown_until,
    )
    if not armed:
        return BreakevenResetDecisionV1(ACTION_HOLD, updated, "waiting for profit-zone arm")

    # Once profit has existed, do not permit the position to drift materially through
    # entry. A small positive band absorbs quote/spread noise around exact breakeven.
    if favourable <= max(0.0, float(config.breakeven_band_bps)):
        until = now + timedelta(seconds=max(1, int(config.cooldown_seconds)))
        closed = BreakevenResetStateV1(
            entry_price=state.entry_price,
            direction=state.direction,
            profit_armed=True,
            favourable_extreme=extreme,
            cooldown_until=until,
        )
        return BreakevenResetDecisionV1(
            ACTION_CLOSE,
            closed,
            f"BREAKEVEN_RESET favourable_bps={favourable:.3f} cooldown_until={until.isoformat()}",
        )
    return BreakevenResetDecisionV1(ACTION_HOLD, updated, "profit remains above breakeven band")


def reentry_allowed_v1(*, cooldown_until: datetime | None, now: datetime) -> bool:
    if cooldown_until is None:
        return True
    return _utc(now) >= _utc(cooldown_until)


__all__ = [
    "ACTION_CLOSE",
    "ACTION_HOLD",
    "BreakevenResetConfigV1",
    "BreakevenResetDecisionV1",
    "BreakevenResetStateV1",
    "DEFAULT_BREAKEVEN_BAND_BPS",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MIN_FAVOURABLE_BPS",
    "evaluate_breakeven_reset_v1",
    "reentry_allowed_v1",
]
