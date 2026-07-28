from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable

import pandas as pd


ENGINE_VERSION = "historical-engine-v1"
PRIMARY_HORIZON = "4h"


@dataclass(frozen=True, slots=True)
class HistoricalHorizonAssessment:
    horizon: str
    observations: int
    probability_up: float | None
    probability_down: float | None
    median_return_pct: float | None
    likely_interval_low_pct: float | None
    likely_interval_high_pct: float | None
    broad_interval_low_pct: float | None
    broad_interval_high_pct: float | None
    direction: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HistoricalAssessment:
    assessment_id: str
    source_search_id: str
    asset: str
    engine_version: str
    generated_at: str
    status: str
    primary_horizon: str
    forecast_direction: str
    probability_up: float | None
    probability_down: float | None
    expected_return_pct: float | None
    likely_interval_low_pct: float | None
    likely_interval_high_pct: float | None
    broad_interval_low_pct: float | None
    broad_interval_high_pct: float | None
    confidence: float
    independent_analogues: int
    raw_reactions: int
    duplicate_reactions_removed: int
    horizons: tuple[HistoricalHorizonAssessment, ...]
    invalidation_conditions: tuple[str, ...]
    limitations: tuple[str, ...]
    calibration_target: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["horizons"] = [item.to_record() for item in self.horizons]
        return record


def _finite_values(rows: Iterable[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = pd.to_numeric(row.get(field), errors="coerce")
        if pd.isna(value):
            continue
        values.append(float(value))
    return values


def _deduplicate_reactions(reactions: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    rows = [dict(row) for row in reactions]
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        published_at = str(row.get("published_at") or "").strip()
        event_id = str(row.get("candidate_event_id") or "").strip()
        key = published_at or event_id
        if not key:
            key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique, len(rows), len(rows) - len(unique)


def _direction(probability_up: float | None, *, threshold: float = 0.60) -> str:
    if probability_up is None:
        return "INSUFFICIENT_DATA"
    if probability_up >= threshold:
        return "UP"
    if probability_up <= 1.0 - threshold:
        return "DOWN"
    return "MIXED"


def _horizon(rows: list[dict[str, Any]], *, horizon: str, field: str) -> HistoricalHorizonAssessment:
    values = _finite_values(rows, field)
    if not values:
        return HistoricalHorizonAssessment(
            horizon=horizon,
            observations=0,
            probability_up=None,
            probability_down=None,
            median_return_pct=None,
            likely_interval_low_pct=None,
            likely_interval_high_pct=None,
            broad_interval_low_pct=None,
            broad_interval_high_pct=None,
            direction="INSUFFICIENT_DATA",
        )

    series = pd.Series(values, dtype="float64")
    probability_up = float((series > 0).mean())
    probability_down = float((series < 0).mean())
    return HistoricalHorizonAssessment(
        horizon=horizon,
        observations=len(values),
        probability_up=probability_up,
        probability_down=probability_down,
        median_return_pct=float(series.median()),
        likely_interval_low_pct=float(series.quantile(0.25)),
        likely_interval_high_pct=float(series.quantile(0.75)),
        broad_interval_low_pct=float(series.quantile(0.10)),
        broad_interval_high_pct=float(series.quantile(0.90)),
        direction=_direction(probability_up),
    )


def _confidence(primary: HistoricalHorizonAssessment) -> float:
    if primary.observations == 0 or primary.probability_up is None:
        return 0.0
    sample_component = min(primary.observations / 10.0, 1.0)
    directional_component = abs(primary.probability_up - 0.5) * 2.0
    return round(0.5 * sample_component + 0.5 * directional_component, 4)


def build_historical_assessment(
    reactions: Iterable[dict[str, Any]],
    *,
    source_search_id: str,
    asset: str = "Brent",
    semantic_filter_applied: bool = False,
) -> HistoricalAssessment:
    unique, raw_count, duplicate_count = _deduplicate_reactions(reactions)
    usable = [row for row in unique if str(row.get("status") or "") == "OK"]

    horizons = (
        _horizon(usable, horizon="15m", field="return_15m_pct"),
        _horizon(usable, horizon="1h", field="return_1h_pct"),
        _horizon(usable, horizon="4h", field="return_4h_pct"),
        _horizon(usable, horizon="24h", field="return_24h_pct"),
    )
    primary = next(item for item in horizons if item.horizon == PRIMARY_HORIZON)
    confidence = _confidence(primary)

    invalidation: list[str] = []
    if primary.observations < 5:
        invalidation.append("Fewer than five independent analogues have valid 4-hour prices.")
    if primary.direction == "MIXED":
        invalidation.append("Directional agreement is below 60 percent.")
    invalidation.extend(
        [
            "A materially different current market regime can invalidate the historical transfer.",
            "The forecast is stale if the current move is already outside the broad historical interval before use.",
        ]
    )
    if not semantic_filter_applied:
        invalidation.insert(0, "Semantic ranking has not been applied to the retained events.")

    limitations = [
        "Candidate reactions are deduplicated by exact publication timestamp.",
        "Market-regime and conflict-regime filtering are not yet applied.",
        "The output is a historical conditional forecast, not a standalone trade recommendation.",
    ]
    if semantic_filter_applied:
        limitations.insert(1, "Only candidates passing the current semantic thresholds are included.")
    else:
        limitations.insert(1, "This version has not yet applied semantic analogue ranking.")

    if primary.observations == 0:
        status = "INSUFFICIENT_DATA"
    elif primary.observations < 5:
        status = "LOW_SAMPLE_EVENT_RANKED" if semantic_filter_applied else "LOW_SAMPLE_UNRANKED"
    else:
        status = "EVENT_RANKED_CONTEXT_PENDING" if semantic_filter_applied else "PROVISIONAL_UNRANKED"

    identity = {
        "source_search_id": source_search_id,
        "asset": asset,
        "engine_version": ENGINE_VERSION,
        "semantic_filter_applied": semantic_filter_applied,
        "event_ids": sorted(str(row.get("candidate_event_id") or "") for row in usable),
        "published_at": sorted(str(row.get("published_at") or "") for row in usable),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    assessment_id = "historical-assessment:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]

    return HistoricalAssessment(
        assessment_id=assessment_id,
        source_search_id=source_search_id,
        asset=asset,
        engine_version=ENGINE_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        primary_horizon=PRIMARY_HORIZON,
        forecast_direction=primary.direction,
        probability_up=primary.probability_up,
        probability_down=primary.probability_down,
        expected_return_pct=primary.median_return_pct,
        likely_interval_low_pct=primary.likely_interval_low_pct,
        likely_interval_high_pct=primary.likely_interval_high_pct,
        broad_interval_low_pct=primary.broad_interval_low_pct,
        broad_interval_high_pct=primary.broad_interval_high_pct,
        confidence=confidence,
        independent_analogues=primary.observations,
        raw_reactions=raw_count,
        duplicate_reactions_removed=duplicate_count,
        horizons=horizons,
        invalidation_conditions=tuple(invalidation),
        limitations=tuple(limitations),
        calibration_target="realized_return_4h_pct",
    )
