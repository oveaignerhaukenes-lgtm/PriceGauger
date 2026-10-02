from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


STATE_OFF = "OFF"
STATE_ARMED = "ARMED"
STATE_LIVE = "LIVE"
STATE_BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class V2PreflightV1:
    account_id: str
    instrument_label: str
    strategy_label: str
    timeframe_label: str
    currency: str
    allocated_capital: float
    exposure_pct: float
    amount: float | None
    notional: float | None
    effective_leverage: float | None
    minimum_amount: float | None
    minimum_capital: float | None
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(self.amount is not None and self.amount > 0 and not self.blockers)


@dataclass(frozen=True, slots=True)
class V2CockpitStateV1:
    state: str
    live_requested: bool
    guard_blocked: bool
    guard_reason: str | None
    observed_direction: str
    desired_direction: str | None
    last_decision: str | None = None
    last_broker_action: str | None = None
    reconciled_at: str | None = None

    @property
    def indicator(self) -> str:
        if self.state == STATE_LIVE:
            return "RECORD"
        if self.state == STATE_BLOCKED:
            return "ALERT"
        if self.state == STATE_ARMED:
            return "ARMED"
        return "OFF"


def normalize_blockers_v1(values: Iterable[str | None]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def cockpit_state_v1(
    *,
    live_requested: bool,
    guard_blocked: bool,
    guard_reason: str | None,
    preflight_ready: bool,
    observed_direction: str,
    desired_direction: str | None,
    last_decision: str | None = None,
    last_broker_action: str | None = None,
    reconciled_at: str | None = None,
) -> V2CockpitStateV1:
    """Derive the one user-facing V2 state without granting execution authority.

    ARMED means configuration/preflight is ready but LIVE authority is off.
    LIVE means the user explicitly requested LIVE and no runtime guard is active.
    BLOCKED preserves the user's LIVE intent while making the runtime interlock visible.
    """
    if guard_blocked:
        state = STATE_BLOCKED
    elif live_requested:
        state = STATE_LIVE
    elif preflight_ready:
        state = STATE_ARMED
    else:
        state = STATE_OFF
    return V2CockpitStateV1(
        state=state,
        live_requested=bool(live_requested),
        guard_blocked=bool(guard_blocked),
        guard_reason=(str(guard_reason).strip() if guard_reason else None),
        observed_direction=str(observed_direction or "FLAT").upper(),
        desired_direction=(str(desired_direction).upper() if desired_direction else None),
        last_decision=last_decision,
        last_broker_action=last_broker_action,
        reconciled_at=reconciled_at,
    )


def minimum_capital_for_notional_v1(notional: float | None, max_effective_leverage: float | None) -> float | None:
    if notional is None or max_effective_leverage is None:
        return None
    n = float(notional)
    leverage = float(max_effective_leverage)
    if n <= 0 or leverage <= 0:
        return None
    return n / leverage


__all__ = [
    "STATE_OFF",
    "STATE_ARMED",
    "STATE_LIVE",
    "STATE_BLOCKED",
    "V2PreflightV1",
    "V2CockpitStateV1",
    "normalize_blockers_v1",
    "cockpit_state_v1",
    "minimum_capital_for_notional_v1",
]
