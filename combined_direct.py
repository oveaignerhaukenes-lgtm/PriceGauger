from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from asset_state_mapping import AssetRecommendation
from market_interpretation import MarketInterpretation
from technical_regime import TechnicalRegime


_DIRECTION_SCORES = {
    "SHORT": -1.0,
    "BEARISH": -1.0,
    "SLIGHTLY BEARISH": -0.5,
    "NEUTRAL": 0.0,
    "SLIGHTLY BULLISH": 0.5,
    "BULLISH": 1.0,
    "LONG": 1.0,
}

_QUALITY_WEIGHTS = {
    "INSUFFICIENT": 0.0,
    "LOW": 0.35,
    "MEDIUM": 0.70,
    "HIGH": 1.0,
}


@dataclass(frozen=True, slots=True)
class CombinedDirectAssessment:
    event_id: str
    asset: str
    event_bias: str
    event_confidence: float
    event_signal_strength: int
    technical_bias: str
    technical_signal_quality: str
    alignment: str
    combined_bias: str
    combined_confidence: float
    review_interval_minutes: int
    review_label: str
    technical_sources: tuple[str, ...]
    data_quality: str
    rationale: tuple[str, ...]
    schema_version: str = "combined-direct-v1"

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["technical_sources"] = list(self.technical_sources)
        record["rationale"] = list(self.rationale)
        return record


def _direction_score(direction: str) -> float:
    try:
        return _DIRECTION_SCORES[direction.upper()]
    except KeyError as exc:
        raise ValueError(f"unsupported direction or bias: {direction}") from exc


def _combined_bias(score: float) -> str:
    if score >= 0.70:
        return "BULLISH"
    if score >= 0.20:
        return "SLIGHTLY BULLISH"
    if score <= -0.70:
        return "BEARISH"
    if score <= -0.20:
        return "SLIGHTLY BEARISH"
    return "NEUTRAL"


def _alignment(event_score: float, technical_score: float, technical_weight: float) -> str:
    if technical_weight == 0.0:
        return "TECHNICAL INSUFFICIENT"
    if event_score == 0.0 and technical_score == 0.0:
        return "NEUTRAL"
    if event_score == 0.0 or technical_score == 0.0:
        return "PARTIAL"
    return "ALIGNED" if event_score * technical_score > 0 else "CONFLICT"


def _source_status(sources: Mapping[str, str]) -> tuple[tuple[str, ...], str]:
    normalized = tuple(sorted({str(value).strip() for value in sources.values() if str(value).strip()}))
    if not normalized:
        return (), "UNKNOWN"
    saxo_count = sum(source.lower().startswith("saxo") for source in normalized)
    if saxo_count == len(normalized):
        return normalized, "PRIMARY"
    if saxo_count:
        return normalized, "MIXED"
    return normalized, "FALLBACK"


def build_combined_direct_assessment(
    interpretation: MarketInterpretation,
    recommendation: AssetRecommendation,
    technical: TechnicalRegime,
    *,
    technical_sources: Mapping[str, str],
    direct_weight: float = 0.65,
    technical_weight: float = 0.35,
) -> CombinedDirectAssessment:
    if recommendation.asset.strip() == "":
        raise ValueError("recommendation asset must not be empty")
    if direct_weight < 0.0 or technical_weight < 0.0 or direct_weight + technical_weight <= 0.0:
        raise ValueError("analysis weights must be non-negative and have a positive sum")

    event_score = _direction_score(recommendation.direction)
    technical_score = _direction_score(technical.bias)
    technical_quality_weight = _QUALITY_WEIGHTS.get(technical.signal_quality.upper())
    if technical_quality_weight is None:
        raise ValueError(f"unsupported technical signal quality: {technical.signal_quality}")

    event_confidence = max(
        0.0,
        min(
            1.0,
            interpretation.confidence
            * interpretation.source_quality
            * (recommendation.signal_strength / 100.0),
        ),
    )
    effective_direct_weight = direct_weight * event_confidence
    effective_technical_weight = technical_weight * technical_quality_weight
    denominator = effective_direct_weight + effective_technical_weight
    combined_score = 0.0
    if denominator:
        combined_score = (
            event_score * effective_direct_weight
            + technical_score * effective_technical_weight
        ) / denominator

    alignment = _alignment(event_score, technical_score, technical_quality_weight)
    agreement_factor = {
        "ALIGNED": 1.0,
        "PARTIAL": 0.80,
        "NEUTRAL": 0.65,
        "TECHNICAL INSUFFICIENT": 0.75,
        "CONFLICT": 0.50,
    }[alignment]
    raw_confidence = (
        direct_weight * event_confidence
        + technical_weight * technical_quality_weight
    ) / (direct_weight + technical_weight)
    combined_confidence = max(0.0, min(1.0, raw_confidence * agreement_factor))
    sources, data_quality = _source_status(technical_sources)

    reasons = [
        (
            f"Direct event signal for {recommendation.asset}: {recommendation.direction} "
            f"with strength {recommendation.signal_strength}/100."
        ),
        (
            f"Event confidence after source quality and signal strength: "
            f"{event_confidence:.2f}."
        ),
        (
            f"Technical regime: {technical.bias} with {technical.signal_quality} signal quality."
        ),
        f"Layer relationship: {alignment}.",
        f"Technical data quality: {data_quality} ({', '.join(sources) if sources else 'unknown source'}).",
    ]
    reasons.extend(recommendation.rationale)
    reasons.extend(technical.rationale)

    return CombinedDirectAssessment(
        event_id=interpretation.event_id,
        asset=recommendation.asset,
        event_bias=recommendation.direction,
        event_confidence=round(event_confidence, 6),
        event_signal_strength=recommendation.signal_strength,
        technical_bias=technical.bias,
        technical_signal_quality=technical.signal_quality,
        alignment=alignment,
        combined_bias=_combined_bias(combined_score),
        combined_confidence=round(combined_confidence, 6),
        review_interval_minutes=technical.review_interval_minutes,
        review_label=technical.review_label,
        technical_sources=sources,
        data_quality=data_quality,
        rationale=tuple(reasons),
    )
