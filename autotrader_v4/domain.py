"""Pure contracts for a new AutoTrader; no network, database or order privileges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum


def _require_aware(at: datetime) -> datetime:
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return at.astimezone(timezone.utc)


def _decimal(value: str | Decimal) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Use a decimal string, not a binary float, for money/size")
    try:
        parsed = Decimal(value)
    except (TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid decimal") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    return parsed


@dataclass(frozen=True, slots=True)
class SaxoBoundary:
    account_id: str
    uic: int
    asset_type: str

    def __post_init__(self) -> None:
        if not self.account_id.strip() or int(self.uic) <= 0 or not self.asset_type.strip():
            raise ValueError("Exact account, UIC and asset type are required")


@dataclass(frozen=True, slots=True)
class StrategyRef:
    key: str
    version: str
    config_digest: str

    def __post_init__(self) -> None:
        if not all((self.key.strip(), self.version.strip(), self.config_digest.strip())):
            raise ValueError("Strategy key, version and immutable config digest required")


@dataclass(frozen=True, slots=True)
class BboObservation:
    boundary: SaxoBoundary
    observed_at: datetime
    bid: Decimal
    ask: Decimal
    provider_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _require_aware(self.observed_at))
        if self.provider_at is not None:
            object.__setattr__(self, "provider_at", _require_aware(self.provider_at))
        bid, ask = _decimal(self.bid), _decimal(self.ask)
        if bid <= 0 or ask <= 0 or bid > ask:
            raise ValueError("Bid/ask must be positive and ordered")
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)

    def is_fresh(self, *, now: datetime, max_age_seconds: float) -> bool:
        stamp = _require_aware(now)
        if max_age_seconds <= 0:
            return False
        received_age = (stamp - self.observed_at).total_seconds()
        if received_age < 0 or received_age > max_age_seconds:
            return False
        # A delayed provider timestamp is never promoted to LIVE merely because
        # it was received recently; missing provider time needs explicit separate
        # verification at the Saxo gateway boundary.
        if self.provider_at is None:
            return False
        source_age = (stamp - self.provider_at).total_seconds()
        return 0 <= source_age <= max_age_seconds


@dataclass(frozen=True, slots=True)
class TradeDecision:
    boundary: SaxoBoundary
    strategy: StrategyRef
    decision_at: datetime
    evidence_cutoff: datetime
    desired_signed_units: Decimal
    decision_key: str

    def __post_init__(self) -> None:
        decision_at = _require_aware(self.decision_at)
        cutoff = _require_aware(self.evidence_cutoff)
        if cutoff > decision_at:
            raise ValueError("Future market evidence cannot inform a decision")
        if not self.decision_key.strip():
            raise ValueError("Decision idempotency key is required")
        object.__setattr__(self, "decision_at", decision_at)
        object.__setattr__(self, "evidence_cutoff", cutoff)
        object.__setattr__(self, "desired_signed_units", _decimal(self.desired_signed_units))


class IntentState(str, Enum):
    RESERVED = "RESERVED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


_ALLOWED = {
    IntentState.RESERVED: frozenset({IntentState.SUBMITTING, IntentState.REJECTED}),
    IntentState.SUBMITTING: frozenset({IntentState.SUBMITTED, IntentState.UNKNOWN, IntentState.REJECTED}),
    IntentState.SUBMITTED: frozenset({IntentState.RECONCILED, IntentState.UNKNOWN, IntentState.REJECTED}),
    IntentState.UNKNOWN: frozenset({IntentState.RECONCILED, IntentState.REJECTED}),
    IntentState.RECONCILED: frozenset(),
    IntentState.REJECTED: frozenset(),
}


def advance_intent_state(
    current: IntentState,
    target: IntentState,
    *,
    broker_evidence: bool = False,
    definitive_rejection: bool = False,
) -> IntentState:
    """Pure transition validation; SQL must additionally enforce atomic CAS.

    An uncertain order can never be marked failed just because a request timed
    out. An authoritative broker response is needed to resolve UNKNOWN.
    """
    current, target = IntentState(current), IntentState(target)
    if target not in _ALLOWED[current]:
        raise ValueError(f"Disallowed order transition: {current.value} -> {target.value}")
    if current == IntentState.UNKNOWN and not broker_evidence:
        raise ValueError("UNKNOWN requires broker evidence to resolve")
    if target == IntentState.RECONCILED and not broker_evidence:
        raise ValueError("RECONCILED requires broker position/order evidence")
    if target == IntentState.REJECTED and current != IntentState.RESERVED and not definitive_rejection:
        raise ValueError("Post-submit REJECTED requires a definitive broker rejection")
    return target
