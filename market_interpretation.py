from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

STATE_NAMES = (
    "conflict_pressure",
    "energy_supply_risk",
    "shipping_risk",
    "safe_haven_pressure",
    "usd_pressure",
)
UPDATE_TYPES = {
    "NEW_EVENT",
    "UPDATE",
    "CONFIRMATION",
    "ESCALATION",
    "DEESCALATION",
    "CORRECTION",
    "CONTEXT",
    "DUPLICATE",
}


def _bounded(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


@dataclass(frozen=True, slots=True)
class MarketInterpretation:
    event_id: str
    cluster_id: str
    published_at: str
    summary: str
    state_deltas: dict[str, float]
    novelty: float
    confidence: float
    source_quality: float
    update_type: str
    evidence: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    schema_version: str = "market-interpretation-v1"
    model_version: str = "unknown"
    prompt_version: str = "interpreter-v1"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MarketInterpretation":
        required = (
            "event_id",
            "cluster_id",
            "published_at",
            "summary",
            "state_deltas",
            "novelty",
            "confidence",
            "source_quality",
            "update_type",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        update_type = str(payload["update_type"]).upper()
        if update_type not in UPDATE_TYPES:
            raise ValueError(f"unsupported update_type: {update_type}")

        raw_deltas = payload["state_deltas"]
        if not isinstance(raw_deltas, Mapping):
            raise ValueError("state_deltas must be an object")
        unknown = sorted(set(raw_deltas) - set(STATE_NAMES))
        missing_states = sorted(set(STATE_NAMES) - set(raw_deltas))
        if unknown or missing_states:
            raise ValueError(
                f"state_deltas must contain exactly {STATE_NAMES}; "
                f"unknown={unknown}, missing={missing_states}"
            )
        deltas = {
            name: _bounded(raw_deltas[name], f"state_deltas.{name}", -1.0, 1.0)
            for name in STATE_NAMES
        }

        published = str(payload["published_at"])
        try:
            parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("published_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("published_at must include a timezone")

        return cls(
            event_id=str(payload["event_id"]).strip(),
            cluster_id=str(payload["cluster_id"]).strip(),
            published_at=parsed.astimezone(timezone.utc).isoformat(),
            summary=str(payload["summary"]).strip(),
            state_deltas=deltas,
            novelty=_bounded(payload["novelty"], "novelty", 0.0, 1.0),
            confidence=_bounded(payload["confidence"], "confidence", 0.0, 1.0),
            source_quality=_bounded(payload["source_quality"], "source_quality", 0.0, 1.0),
            update_type=update_type,
            evidence=tuple(str(item) for item in payload.get("evidence", ())),
            uncertainties=tuple(str(item) for item in payload.get("uncertainties", ())),
            schema_version=str(payload.get("schema_version", "market-interpretation-v1")),
            model_version=str(payload.get("model_version", "unknown")),
            prompt_version=str(payload.get("prompt_version", "interpreter-v1")),
        )

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["evidence"] = list(self.evidence)
        record["uncertainties"] = list(self.uncertainties)
        return record
