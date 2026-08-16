from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from context_snapshot_v2 import ContextSnapshotV2, ContextTargetStateV2, FRESH
from technical_core_v2 import TechnicalBaselineForecast


HOLISTIC_COMPOSER_V1_RECIPE = "holistic-composer-v1.0"


@dataclass(frozen=True, slots=True)
class HolisticProvenanceV1:
    technical_recipe: str
    technical_as_of: str
    context_snapshot_id: str
    context_fingerprint: str
    context_as_of: str
    context_engine_version: str
    context_freshness: str
    context_target_key: str


@dataclass(frozen=True, slots=True)
class HolisticForecastV1:
    market: str
    as_of: str
    horizon_seconds: int
    recipe_version: str
    baseline_return: float
    composed_return: float
    lower_return: float
    upper_return: float
    direction: str
    path_shape: str
    technical_confidence: float
    context_bias: float
    context_confidence: float
    context_event_risk: float
    context_novelty: float
    context_applied: bool
    provenance: HolisticProvenanceV1

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_record(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()


def _target_for_market(context: ContextSnapshotV2, market: str) -> ContextTargetStateV2 | None:
    normalized = str(market).strip().casefold()
    for target in context.targets:
        if target.target_key.strip().casefold() == normalized:
            return target
    return None


def compose_holistic_forecast_v1(
    *,
    technical: TechnicalBaselineForecast,
    context: ContextSnapshotV2,
    recipe_version: str = HOLISTIC_COMPOSER_V1_RECIPE,
) -> HolisticForecastV1:
    """Compose independent technical and context snapshots without learned weights.

    Technical Core remains the baseline authority. Context may add one bounded,
    deterministic adjustment only when its canonical snapshot is FRESH and contains
    a matching market target. No LLM, legacy Decision/Recommendation, position or
    execution state is consulted here.
    """
    target = _target_for_market(context, technical.market)
    context_applied = context.freshness_status == FRESH and target is not None

    expected = float(technical.expected_return)
    lower = float(technical.lower_return)
    upper = float(technical.upper_return)
    baseline_width = max(0.0, upper - lower)

    bias = float(target.directional_bias) if target is not None else 0.0
    confidence = float(target.confidence) if target is not None else 0.0
    event_risk = float(target.event_risk) if target is not None else 0.0
    novelty = float(target.novelty) if target is not None else 0.0

    if context_applied:
        # Fixed v1 composition rule: context can refine, never replace, Technical Core.
        magnitude = max(abs(expected), baseline_width / 2.0, 0.0005)
        shift = bias * confidence * magnitude * 0.25
        expected += shift

        # Novel event risk widens uncertainty. This is intentionally bounded and
        # deterministic until evaluation data justifies learned composition.
        risk = max(0.0, min(1.0, event_risk * (0.5 + 0.5 * novelty)))
        half_width = (baseline_width / 2.0) * (1.0 + 0.30 * risk)
        lower = expected - half_width
        upper = expected + half_width

    direction = "BULLISH" if expected > 0 else "BEARISH" if expected < 0 else "NEUTRAL"
    provenance = HolisticProvenanceV1(
        technical_recipe=technical.recipe_version,
        technical_as_of=technical.as_of,
        context_snapshot_id=context.snapshot_id,
        context_fingerprint=context.state_fingerprint,
        context_as_of=context.as_of,
        context_engine_version=context.engine_version,
        context_freshness=context.freshness_status,
        context_target_key=target.target_key if target is not None else "",
    )
    return HolisticForecastV1(
        market=technical.market,
        as_of=technical.as_of,
        horizon_seconds=technical.horizon_seconds,
        recipe_version=recipe_version,
        baseline_return=technical.expected_return,
        composed_return=round(expected, 8),
        lower_return=round(lower, 8),
        upper_return=round(upper, 8),
        direction=direction,
        path_shape=technical.path_shape,
        technical_confidence=technical.confidence,
        context_bias=bias,
        context_confidence=confidence,
        context_event_risk=event_risk,
        context_novelty=novelty,
        context_applied=context_applied,
        provenance=provenance,
    )
