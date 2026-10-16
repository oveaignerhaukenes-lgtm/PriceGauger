"""Avoid Loss V1 — deterministic broker-margin-normalized risk policy.

Pure decision model. It does NOT submit Saxo orders, register as LIVE-ready,
or invent leverage from underlying price movements.

Every P/L sample must be exact-account, exact-product, base-currency NOK,
fresh and reliable. Denominator is entry-time margin frozen for the exact
confirmed position lifecycle (not current margin, price, contract notional,
or total account balance). For LIVE, close decisions must eventually use
V3 durable CLOSE/reconciliation and a sufficiently fast risk loop.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite

STRATEGY_KEY_V1 = "avoid-loss-v1"
LOSS_STOP_PCT = -1.0
TRAIL_ACTIVATE_PCT = 2.0
PEAK_GIVEBACK = 0.10
SIGNAL_MINUTES = 2
MAX_SAMPLE_AGE_SECONDS = 10
CURRENCY = "NOK"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be datetime")
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite(value, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class AvoidLossSettingsV1:
    loss_stop_pct: float = LOSS_STOP_PCT
    trail_activation_pct: float = TRAIL_ACTIVATE_PCT
    peak_giveback: float = PEAK_GIVEBACK
    max_sample_age_seconds: int = MAX_SAMPLE_AGE_SECONDS

    def __post_init__(self):
        stop = _finite(self.loss_stop_pct, name="loss stop")
        threshold = _finite(self.trail_activation_pct, name="trailing activation")
        fraction = _finite(self.peak_giveback, name="giveback")
        if not (-100 < stop < 0) or threshold <= 0 or not (0 < fraction < 1):
            raise ValueError("invalid Avoid Loss risk policy")
        if not (0 < int(self.max_sample_age_seconds) <= 60):
            raise ValueError("invalid freshness policy")


@dataclass(frozen=True)
class ConfirmedPositionV1:
    """Saxo-supported lifecycle frozen by the exact execution ledger.

    margin_nok is the ORIGINAL Saxo entry precheck margin for the exact
    confirmed position. If size changed after this anchor, retire it rather
    than silently reusing the denominator for a different exposure.
    """
    account_id: str
    uic: int
    asset_type: str
    position_token: str
    signed_amount: float
    entry_margin_nok: float

    def __post_init__(self):
        if not all([self.account_id, self.asset_type, self.position_token]):
            raise ValueError("position boundary incomplete")
        amount = _finite(self.signed_amount, name="amount")
        capital = _finite(self.entry_margin_nok, name="entry margin")
        if amount == 0 or capital <= 0 or self.uic <= 0:
            raise ValueError("position and frozen positive entry margin required")

    @property
    def key(self):
        return (self.account_id, int(self.uic), self.asset_type,
                self.position_token, self.signed_amount)


@dataclass(frozen=True)
class BrokerPnLSampleV1:
    """NET mark-to-liquidate P/L in the SAME account currency as margin.

    Base-currency trade P/L plus explicitly validated FX/cost components,
    minus accrued costs and projected exit costs. No made-up zero defaults.
    """
    position_key: tuple
    mark_to_liquidate_nok: float
    currency: str
    as_of: datetime
    reliability: str
    quote_delay_minutes: int
    has_verified_costs: bool

    def __post_init__(self):
        _finite(self.mark_to_liquidate_nok, name="net P/L")
        _utc(self.as_of)
        if not self.position_key:
            raise ValueError("position identity required")


@dataclass(frozen=True)
class AvoidLossStateV1:
    """Durable per-account-and-position high water and stop latch.

    exit_pending is sticky until exact broker FLAT is reconciled.
    No old strategy signal can flip the target while close is pending.
    """
    position_key: tuple
    peak_pct: float
    trailing_armed: bool = False
    exit_pending: bool = False
    exit_reason: str | None = None
    last_sample_at: datetime | None = None

    def __post_init__(self):
        _finite(self.peak_pct, name="peak")
        if self.last_sample_at is not None:
            _utc(self.last_sample_at)


@dataclass(frozen=True)
class AvoidLossDecisionV1:
    action: str
    reason: str
    pnl_pct: float | None
    peak_pct: float | None
    floor_pct: float | None
    state: AvoidLossStateV1 | None


def inspect_open_position_v1(
    *,
    position: ConfirmedPositionV1,
    sample: BrokerPnLSampleV1,
    state: AvoidLossStateV1 | None,
    now: datetime,
    policy: AvoidLossSettingsV1 = AvoidLossSettingsV1(),
) -> AvoidLossDecisionV1:
    """Read-only risk transition; STOP means *request durable CLOSE*, not a fill.

    On missing/unverifiable data, emit BLOCKED and leave high-water untouched.
    The caller must surface the unprotected-position warning, never advertise
    that a 1% stop was successfully enforced.
    """
    current_time = _utc(now)
    if sample.position_key != position.key:
        return AvoidLossDecisionV1("BLOCKED","position identity mismatch",None,
                                   state.peak_pct if state else None,None,state)
    if state is not None and state.position_key != position.key:
        return AvoidLossDecisionV1("BLOCKED","position changed; margin anchor must be revalidated",None,
                                   state.peak_pct,None,state)
    if (sample.currency != CURRENCY or not sample.has_verified_costs
        or sample.reliability.strip().lower() != "ok"
        or sample.quote_delay_minutes != 0):
        return AvoidLossDecisionV1(
            "BLOCKED","Saxo P/L currency/reliability/cost evidence unavailable",
            None,state.peak_pct if state else None,None,state)
    age = (current_time-_utc(sample.as_of)).total_seconds()
    if age < 0 or age > policy.max_sample_age_seconds:
        return AvoidLossDecisionV1(
            "BLOCKED",f"stale or future Saxo sample ({age:.1f}s)",
            None,state.peak_pct if state else None,None,state)
    if state is not None and state.last_sample_at is not None:
        if _utc(sample.as_of) < _utc(state.last_sample_at):
            return AvoidLossDecisionV1(
                "BLOCKED","non-monotonic Saxo P/L sample",None,state.peak_pct,None,state)
    pnl_pct = 100.0*_finite(sample.mark_to_liquidate_nok,name="P/L")/position.entry_margin_nok
    if state is None:
        peak = pnl_pct
        armed = peak >= policy.trail_activation_pct
        current = AvoidLossStateV1(
            position.key, peak, armed, last_sample_at=sample.as_of)
    else:
        peak = max(float(state.peak_pct), pnl_pct)
        armed = bool(state.trailing_armed or peak >= policy.trail_activation_pct)
        current = replace(state,peak_pct=peak,trailing_armed=armed,
                          last_sample_at=sample.as_of)
    floor = peak*(1.0-policy.peak_giveback) if armed else None
    if current.exit_pending:
        return AvoidLossDecisionV1("WAIT_RECONCILE",
            "CLOSE already requested; do not reopen, retry or reverse",
            pnl_pct,peak,floor,current)
    reason = None
    if pnl_pct <= policy.loss_stop_pct:
        reason = "LOSS_STOP"
    elif floor is not None and pnl_pct <= floor:
        reason = "PEAK_GIVEBACK"
    if reason:
        current = replace(current,exit_pending=True,exit_reason=reason)
        return AvoidLossDecisionV1("REQUEST_CLOSE",reason,pnl_pct,peak,floor,current)
    return AvoidLossDecisionV1("HOLD","open position; no protective threshold crossed",
                                pnl_pct,peak,floor,current)


@dataclass(frozen=True)
class AvoidLossEntrySignalV1:
    """Last *fully confirmed* MACD-2m observation and price breakout evidence."""
    confirmed_at: datetime
    prior_histogram: float
    histogram: float
    breakout_direction: int
    expected_opportunity_pct: float
    estimated_round_trip_cost_pct: float

    def __post_init__(self):
        _utc(self.confirmed_at)
        for name in ("prior_histogram","histogram","expected_opportunity_pct",
                     "estimated_round_trip_cost_pct"):
            _finite(getattr(self,name),name=name)
        if self.breakout_direction not in (-1,0,1):
            raise ValueError("breakout direction must be -1/0/+1")


@dataclass(frozen=True)
class AvoidLossReentryV1:
    eligible_after: datetime
    last_closed_direction: int

    def __post_init__(self):
        _utc(self.eligible_after)
        if self.last_closed_direction not in (-1,0,1):
            raise ValueError("invalid previous direction")


def evaluate_flat_entry_v1(
    *,
    signal: AvoidLossEntrySignalV1,
    last_exit: AvoidLossReentryV1 | None,
    now: datetime,
    policy: AvoidLossSettingsV1 = AvoidLossSettingsV1(),
) -> tuple[int,str]:
    """No new trade without a NEW completed MACD 2m candle and enough room.

    Either histogram ZERO crossing, or histogram magnitude accelerating
    with a *confirmed* same-direction breakout. Assumed opportunity estimate
    is NOT a forecast: must be supplied by independent volatility research.
    """
    clock = _utc(now)
    closed = _utc(signal.confirmed_at)
    if closed > clock or (clock-closed)>timedelta(minutes=2):
        return (0,"STALE_MACD_2M")
    if last_exit is not None and closed <= _utc(last_exit.eligible_after):
        return (0,"WAIT_NEW_CLOSED_BAR")
    margin = policy.trail_activation_pct+signal.estimated_round_trip_cost_pct
    if (signal.estimated_round_trip_cost_pct < 0
        or signal.expected_opportunity_pct < margin):
        return (0,"FLAT_OPPORTUNITY_TOO_SMALL")
    p,h = signal.prior_histogram,signal.histogram
    cross_long = p <= 0 < h
    cross_short = p >= 0 > h
    growing_long = h>0 and h>p and signal.breakout_direction==1
    growing_short = h<0 and h<p and signal.breakout_direction==-1
    if cross_long or growing_long:
        return (1,"LONG_NEW_MACD_SIGNAL")
    if cross_short or growing_short:
        return (-1,"SHORT_NEW_MACD_SIGNAL")
    return (0,"FLAT_NO_DIRECTION")


__all__=[
    "STRATEGY_KEY_V1","LOSS_STOP_PCT","TRAIL_ACTIVATE_PCT","PEAK_GIVEBACK",
    "AvoidLossSettingsV1","ConfirmedPositionV1","BrokerPnLSampleV1",
    "AvoidLossStateV1","AvoidLossDecisionV1","inspect_open_position_v1",
    "AvoidLossEntrySignalV1","AvoidLossReentryV1","evaluate_flat_entry_v1",
]
