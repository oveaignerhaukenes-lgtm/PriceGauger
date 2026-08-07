from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping


STATE_CONTRACT_VERSION = "state-contracts-v1"
DECISION_DIRECTIONS = (
    "LONG_BIAS",
    "SHORT_BIAS",
    "NEUTRAL",
    "CONFLICTED",
    "INSUFFICIENT_DATA",
    "STALE",
)
ALERT_STATUSES = ("WATCH", "ACTIVE", "CONFIRMED", "REJECTED", "EXPIRED", "SUPERSEDED")
ALERT_SEVERITIES = ("WATCH", "ALERT", "CRITICAL")


def _utc_iso(value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(timezone.utc).isoformat()


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    observed_at: str
    age_seconds: int
    freshness: str
    provider: str
    instrument: str
    engine_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc_iso(self.observed_at))
        if self.freshness not in {"FRESH", "STALE", "MISSING"}:
            raise ValueError("freshness must be FRESH, STALE or MISSING")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InformationStateSnapshot:
    snapshot_id: str
    as_of: str
    event_cluster_count: int
    active_event_count: int
    conflict_regime: str
    ceasefire_active: bool
    narrative_saturation: float
    confirmation_quality: float
    supply_risk: float
    source_channels: tuple[str, ...]
    component: ComponentStatus
    state_values: dict[str, float] | None = None
    state_change: dict[str, float] | None = None
    processed_event_ids: tuple[str, ...] = ()
    active_cluster_ids: tuple[str, ...] = ()
    context_as_of: str = ""
    context_engine_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc_iso(self.as_of))
        object.__setattr__(self, "state_values", dict(self.state_values or {}))
        object.__setattr__(self, "state_change", dict(self.state_change or {}))

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["source_channels"] = list(self.source_channels)
        record["processed_event_ids"] = list(self.processed_event_ids)
        record["active_cluster_ids"] = list(self.active_cluster_ids)
        return record


@dataclass(frozen=True, slots=True)
class MarketStateSnapshot:
    snapshot_id: str
    market: str
    as_of: str
    price: float | None
    direction_score: float
    volatility_score: float
    momentum_score: float
    price_confirmation: float
    regime: str
    component: ComponentStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc_iso(self.as_of))
        object.__setattr__(self, "direction_score", _bounded(self.direction_score, -1.0, 1.0))
        object.__setattr__(self, "volatility_score", _bounded(self.volatility_score))
        object.__setattr__(self, "momentum_score", _bounded(self.momentum_score, -1.0, 1.0))
        object.__setattr__(self, "price_confirmation", _bounded(self.price_confirmation, -1.0, 1.0))

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventContribution:
    event_id: str
    event_cluster_id: str
    market: str
    observed_at: str
    direction_nudge: float
    confidence_nudge: float
    expected_move_low_pct: float
    expected_move_high_pct: float
    horizon_hours: float
    novelty: float
    source_quality: float
    confirmation_status: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _utc_iso(self.observed_at))
        object.__setattr__(self, "direction_nudge", _bounded(self.direction_nudge, -1.0, 1.0))
        object.__setattr__(self, "confidence_nudge", _bounded(self.confidence_nudge, -1.0, 1.0))
        object.__setattr__(self, "novelty", _bounded(self.novelty))
        object.__setattr__(self, "source_quality", _bounded(self.source_quality))

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DecisionStateSnapshot:
    snapshot_id: str
    market: str
    as_of: str
    previous_snapshot_id: str
    direction: str
    direction_score: float
    confidence: float
    expected_move_low_pct: float | None
    expected_move_high_pct: float | None
    horizon_hours: float | None
    information_snapshot_id: str
    market_snapshot_id: str
    change_from_previous: float
    contributing_event_ids: tuple[str, ...]
    status_reason: str
    engine_version: str = STATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.direction not in DECISION_DIRECTIONS:
            raise ValueError(f"unsupported direction: {self.direction}")
        object.__setattr__(self, "as_of", _utc_iso(self.as_of))
        object.__setattr__(self, "direction_score", _bounded(self.direction_score, -1.0, 1.0))
        object.__setattr__(self, "confidence", _bounded(self.confidence))
        object.__setattr__(self, "change_from_previous", _bounded(self.change_from_previous, -2.0, 2.0))

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["contributing_event_ids"] = list(self.contributing_event_ids)
        return record


@dataclass(frozen=True, slots=True)
class MarketMoverAlert:
    alert_id: str
    event_cluster_id: str
    created_at: str
    updated_at: str
    status: str
    severity: str
    headline: str
    summary: str
    confirmation_status: str
    source_quality: float
    novelty: float
    market: str
    expected_direction: str
    expected_move_low_pct: float
    expected_move_high_pct: float
    horizon_hours: float
    state_delta: float
    price_confirmation: float
    context_multiplier: float
    rationale: str
    engine_version: str = STATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.status not in ALERT_STATUSES:
            raise ValueError(f"unsupported alert status: {self.status}")
        if self.severity not in ALERT_SEVERITIES:
            raise ValueError(f"unsupported alert severity: {self.severity}")
        object.__setattr__(self, "created_at", _utc_iso(self.created_at))
        object.__setattr__(self, "updated_at", _utc_iso(self.updated_at))
        object.__setattr__(self, "source_quality", _bounded(self.source_quality))
        object.__setattr__(self, "novelty", _bounded(self.novelty))
        object.__setattr__(self, "state_delta", _bounded(self.state_delta, -2.0, 2.0))
        object.__setattr__(self, "price_confirmation", _bounded(self.price_confirmation, -1.0, 1.0))

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def context_multiplier(information: InformationStateSnapshot) -> float:
    """Increase surprise value during calm/ceasefire, damp repetitive reports in saturated war states."""
    multiplier = 1.0
    if information.ceasefire_active:
        multiplier *= 1.55
    if information.conflict_regime.upper() in {"CALM", "DEESCALATING", "CEASEFIRE"}:
        multiplier *= 1.25
    elif information.conflict_regime.upper() in {"ACTIVE_WAR", "HIGH_INTENSITY_WAR"}:
        multiplier *= 0.78
    multiplier *= 1.0 - 0.45 * _bounded(information.narrative_saturation)
    multiplier *= 0.75 + 0.25 * _bounded(information.confirmation_quality)
    return round(max(0.35, min(2.25, multiplier)), 4)


def detect_market_mover(
    contribution: EventContribution,
    information: InformationStateSnapshot,
    market_state: MarketStateSnapshot,
    *,
    headline: str,
    summary: str,
) -> MarketMoverAlert | None:
    expected_abs = max(abs(contribution.expected_move_low_pct), abs(contribution.expected_move_high_pct))
    multiplier = context_multiplier(information)
    significance = (
        expected_abs
        * (0.35 + 0.65 * contribution.source_quality)
        * (0.35 + 0.65 * contribution.novelty)
        * multiplier
    )

    if significance < 0.75 and abs(contribution.direction_nudge) < 0.35:
        return None

    if significance >= 3.5 or (expected_abs >= 4.0 and contribution.source_quality >= 0.55):
        severity = "CRITICAL"
    elif significance >= 1.6 or abs(contribution.direction_nudge) >= 0.65:
        severity = "ALERT"
    else:
        severity = "WATCH"

    status = "CONFIRMED" if abs(market_state.price_confirmation) >= 0.35 else "ACTIVE"
    direction = "UP" if contribution.direction_nudge > 0 else "DOWN" if contribution.direction_nudge < 0 else "UNCERTAIN"
    now = contribution.observed_at
    payload = {
        "event_cluster_id": contribution.event_cluster_id,
        "market": contribution.market,
        "observed_at": now,
        "severity": severity,
    }
    return MarketMoverAlert(
        alert_id=_stable_id("market-mover", payload),
        event_cluster_id=contribution.event_cluster_id,
        created_at=now,
        updated_at=now,
        status=status,
        severity=severity,
        headline=headline,
        summary=summary,
        confirmation_status=contribution.confirmation_status,
        source_quality=contribution.source_quality,
        novelty=contribution.novelty,
        market=contribution.market,
        expected_direction=direction,
        expected_move_low_pct=contribution.expected_move_low_pct,
        expected_move_high_pct=contribution.expected_move_high_pct,
        horizon_hours=contribution.horizon_hours,
        state_delta=contribution.direction_nudge,
        price_confirmation=market_state.price_confirmation,
        context_multiplier=multiplier,
        rationale=(
            f"Context multiplier {multiplier:.2f}; expected move magnitude {expected_abs:.2f}%; "
            f"source quality {contribution.source_quality:.2f}; novelty {contribution.novelty:.2f}."
        ),
    )
