from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


COMPANION_RECIPE_V2 = "analyst-companion-v2.2"
TA_ACTIVITY_MODES = ("QUIET", "NORMAL", "ACTIVE")


@dataclass(frozen=True, slots=True)
class CompanionLevelCandidateV2:
    level_id: str
    kind: str
    price: float
    touches: int
    distance_pct: float

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CompanionAnalysisV2:
    market: str
    as_of: str
    recipe_version: str
    directional_context: str
    breakout_status: str
    pullback_type: str
    squeeze_risk: str
    watched_support_ids: tuple[str, ...]
    watched_resistance_ids: tuple[str, ...]
    confidence: float
    what_changed: str
    commentary: str
    watch_conditions: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["watched_support_ids"] = list(self.watched_support_ids)
        record["watched_resistance_ids"] = list(self.watched_resistance_ids)
        record["watch_conditions"] = list(self.watch_conditions)
        return record


def _utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cluster_extrema(
    values: list[tuple[int, float]],
    *,
    reference_price: float,
    tolerance_fraction: float,
) -> list[tuple[float, int, int]]:
    clusters: list[list[tuple[int, float]]] = []
    for index, price in values:
        matched = None
        for cluster in clusters:
            center = sum(item[1] for item in cluster) / len(cluster)
            if abs(price - center) <= max(abs(reference_price) * tolerance_fraction, 1e-12):
                matched = cluster
                break
        if matched is None:
            clusters.append([(index, price)])
        else:
            matched.append((index, price))
    result: list[tuple[float, int, int]] = []
    for cluster in clusters:
        center = sum(item[1] for item in cluster) / len(cluster)
        touches = len(cluster)
        last_index = max(item[0] for item in cluster)
        result.append((center, touches, last_index))
    return result


def derive_level_candidates_v2(
    price_history: Iterable[tuple[str, float]],
    *,
    max_each_side: int = 3,
) -> tuple[CompanionLevelCandidateV2, ...]:
    """Derive deterministic support/resistance candidates from observed history.

    TA Analyst may choose among these identifiers but must not invent numeric
    support/resistance levels in its structured state.
    """
    points: list[tuple[datetime, float]] = []
    for stamp, raw_price in price_history:
        parsed = _utc(stamp)
        if parsed is not None:
            points.append((parsed, float(raw_price)))
    points.sort(key=lambda item: item[0])
    if len(points) < 3:
        return ()

    prices = [item[1] for item in points[-240:]]
    reference = prices[-1]
    extrema: list[tuple[int, float]] = []
    for index in range(1, len(prices) - 1):
        value = prices[index]
        if value <= prices[index - 1] and value <= prices[index + 1]:
            extrema.append((index, value))
        elif value >= prices[index - 1] and value >= prices[index + 1]:
            extrema.append((index, value))

    if not extrema:
        extrema = [(0, min(prices)), (len(prices) - 1, max(prices))]

    clusters = _cluster_extrema(
        extrema,
        reference_price=reference,
        tolerance_fraction=0.0015,
    )
    supports = [item for item in clusters if item[0] <= reference]
    resistances = [item for item in clusters if item[0] >= reference]

    def rank(items: list[tuple[float, int, int]]) -> list[tuple[float, int, int]]:
        return sorted(
            items,
            key=lambda item: (
                abs(item[0] - reference) / max(abs(reference), 1e-12),
                -item[1],
                -item[2],
            ),
        )[:max_each_side]

    result: list[CompanionLevelCandidateV2] = []
    for offset, (price, touches, _) in enumerate(rank(supports), start=1):
        result.append(
            CompanionLevelCandidateV2(
                level_id=f"S{offset}",
                kind="SUPPORT",
                price=float(price),
                touches=int(touches),
                distance_pct=(float(price) / reference - 1.0) * 100.0,
            )
        )
    for offset, (price, touches, _) in enumerate(rank(resistances), start=1):
        result.append(
            CompanionLevelCandidateV2(
                level_id=f"R{offset}",
                kind="RESISTANCE",
                price=float(price),
                touches=int(touches),
                distance_pct=(float(price) / reference - 1.0) * 100.0,
            )
        )
    return tuple(result)


def _activity_mode(value: str) -> str:
    mode = str(value or "NORMAL").upper()
    if mode not in TA_ACTIVITY_MODES:
        raise ValueError(f"activity_mode must be one of {', '.join(TA_ACTIVITY_MODES)}")
    return mode


def build_companion_payload_v2(
    view,
    *,
    previous_analysis: CompanionAnalysisV2 | None = None,
    activity_mode: str = "NORMAL",
) -> dict[str, Any]:
    history = tuple(getattr(view, "price_history", ()) or ())
    levels = derive_level_candidates_v2(history)
    recent_history = history[-90:]
    return {
        "market": str(view.market),
        "as_of": str(view.as_of),
        "recipe": COMPANION_RECIPE_V2,
        "activity_mode": _activity_mode(activity_mode),
        "technical": {
            "direction": str(view.direction),
            "expected_return": float(view.expected_return),
            "lower_return": float(view.lower_return),
            "upper_return": float(view.upper_return),
            "confidence": float(view.confidence),
            "path_shape": str(view.path_shape),
            "trend_state": str(view.trend_state),
            "momentum_state": str(view.momentum_state),
            "volatility_state": str(view.volatility_state),
            "structure_state": str(view.structure_state),
            "technical_score": float(view.technical_score),
            "horizon_seconds": int(view.horizon_seconds),
        },
        "level_candidates": [item.to_record() for item in levels],
        "recent_price_history": [[str(stamp), float(price)] for stamp, price in recent_history],
        "previous_analysis": None if previous_analysis is None else previous_analysis.to_record(),
    }


def validate_companion_analysis_v2(
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
) -> CompanionAnalysisV2:
    directional = str(record.get("directional_context", "")).upper()
    if directional not in {"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}:
        raise ValueError("invalid directional_context")

    breakout = str(record.get("breakout_status", "")).upper()
    if breakout not in {"NONE", "TESTING", "BREAKOUT", "RETEST", "REJECTION", "FAILED_BREAKOUT"}:
        raise ValueError("invalid breakout_status")

    pullback = str(record.get("pullback_type", "")).upper()
    if pullback not in {"NONE", "NORMAL", "PROFIT_TAKING", "MEAN_REVERSION", "REVERSAL_RISK", "UNDETERMINED"}:
        raise ValueError("invalid pullback_type")

    squeeze = str(record.get("squeeze_risk", "")).upper()
    if squeeze not in {"LOW", "MODERATE", "HIGH", "UNDETERMINED"}:
        raise ValueError("invalid squeeze_risk")

    confidence = float(record.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    candidates = {
        str(item["level_id"]): str(item["kind"])
        for item in payload.get("level_candidates", ())
        if isinstance(item, Mapping) and item.get("level_id") and item.get("kind")
    }

    def ids(name: str, expected_kind: str) -> tuple[str, ...]:
        raw = record.get(name) or ()
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"{name} must be a list")
        values = tuple(str(value) for value in raw)
        if len(values) > 3:
            raise ValueError(f"{name} may contain at most three levels")
        for value in values:
            if candidates.get(value) != expected_kind:
                raise ValueError(f"{name} contains unknown or wrong-kind level {value}")
        return values

    what_changed = str(record.get("what_changed", "")).strip()
    commentary = str(record.get("commentary", "")).strip()
    if not commentary or len(commentary) > 900:
        raise ValueError("commentary is required and must remain concise")
    if len(what_changed) > 360:
        raise ValueError("what_changed must remain concise")

    watch_raw = record.get("watch_conditions") or ()
    if not isinstance(watch_raw, (list, tuple)):
        raise ValueError("watch_conditions must be a list")
    watch_conditions = tuple(str(value).strip() for value in watch_raw if str(value).strip())
    if len(watch_conditions) > 4 or any(len(value) > 240 for value in watch_conditions):
        raise ValueError("watch_conditions must be concise")

    return CompanionAnalysisV2(
        market=str(payload["market"]),
        as_of=str(payload["as_of"]),
        recipe_version=COMPANION_RECIPE_V2,
        directional_context=directional,
        breakout_status=breakout,
        pullback_type=pullback,
        squeeze_risk=squeeze,
        watched_support_ids=ids("watched_support_ids", "SUPPORT"),
        watched_resistance_ids=ids("watched_resistance_ids", "RESISTANCE"),
        confidence=confidence,
        what_changed=what_changed,
        commentary=commentary,
        watch_conditions=watch_conditions,
    )
