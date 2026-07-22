from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import exp, log, sqrt
from typing import Any, Iterable, Mapping

from market_interpretation import MarketInterpretation, STATE_NAMES

_UPDATE_FACTORS = {
    "NEW_EVENT": 1.0,
    "ESCALATION": 1.0,
    "UPDATE": 0.35,
    "CONFIRMATION": 0.15,
    "DEESCALATION": 1.0,
    "CORRECTION": 1.0,
    "CONTEXT": 0.0,
    "DUPLICATE": 0.0,
}


@dataclass(frozen=True, slots=True)
class MarketState:
    as_of: str
    values: dict[str, float]
    change_1h: dict[str, float]
    change_4h: dict[str, float]
    contributors: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["contributors"] = list(self.contributors)
        return record


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def interpretation_weight(
    item: MarketInterpretation,
    *,
    age_hours: float,
    half_life_hours: float = 1.5,
    max_age_hours: float = 6.0,
) -> float:
    if age_hours < 0 or age_hours > max_age_hours:
        return 0.0
    decay = exp(-(log(2.0) / max(0.25, half_life_hours)) * age_hours)
    return (
        _UPDATE_FACTORS[item.update_type]
        * item.novelty
        * item.confidence
        * item.source_quality
        * decay
    )


def build_market_state(
    interpretations: Iterable[MarketInterpretation],
    *,
    as_of: datetime | str,
    half_life_hours: float = 1.5,
    max_age_hours: float = 6.0,
) -> MarketState:
    now = _utc(as_of)
    values = {name: 0.0 for name in STATE_NAMES}
    change_1h = {name: 0.0 for name in STATE_NAMES}
    change_4h = {name: 0.0 for name in STATE_NAMES}
    contributors: list[str] = []

    ordered = sorted(interpretations, key=lambda item: item.published_at)
    for item in ordered:
        timestamp = _utc(item.published_at)
        age_hours = (now - timestamp).total_seconds() / 3600.0
        weight = interpretation_weight(
            item,
            age_hours=age_hours,
            half_life_hours=half_life_hours,
            max_age_hours=max_age_hours,
        )
        if weight == 0.0:
            continue
        contributors.append(item.event_id)
        for name in STATE_NAMES:
            contribution = item.state_deltas[name] * weight
            values[name] = _clamp(values[name] + contribution)
            if age_hours <= 1.0:
                change_1h[name] = _clamp(change_1h[name] + contribution)
            if age_hours <= 4.0:
                change_4h[name] = _clamp(change_4h[name] + contribution)

    return MarketState(
        as_of=now.isoformat(),
        values={name: round(values[name], 6) for name in STATE_NAMES},
        change_1h={name: round(change_1h[name], 6) for name in STATE_NAMES},
        change_4h={name: round(change_4h[name], 6) for name in STATE_NAMES},
        contributors=tuple(contributors),
    )


def state_delta_norm(deltas: Mapping[str, float]) -> float:
    return round(sqrt(sum(float(deltas[name]) ** 2 for name in STATE_NAMES)), 6)
