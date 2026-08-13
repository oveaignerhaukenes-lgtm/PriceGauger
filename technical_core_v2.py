from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from technical_analysis import TechnicalSnapshot, build_multi_timeframe_snapshot


TECHNICAL_CORE_V2_RECIPE = "technical-core-v2.1"


@dataclass(frozen=True, slots=True)
class TechnicalCoreState:
    market: str
    as_of: str
    recipe_version: str
    primary_timeframe: str
    trend_state: str
    momentum_state: str
    volatility_state: str
    structure_state: str
    score: float
    confidence: float
    snapshots: dict[str, dict[str, Any]]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TechnicalBaselineForecast:
    market: str
    as_of: str
    horizon_seconds: int
    recipe_version: str
    direction: str
    expected_return: float
    lower_return: float
    upper_return: float
    confidence: float
    path_shape: str
    technical_state: TechnicalCoreState

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["technical_state"] = self.technical_state.to_record()
        return record


def _bias_value(value: str | None) -> int:
    normalized = (value or "").lower()
    if normalized == "bullish":
        return 1
    if normalized == "bearish":
        return -1
    return 0


def _snapshot_score(snapshot: TechnicalSnapshot) -> tuple[float, int]:
    weighted = 0.0
    weight_total = 0.0
    weights = {
        "trend": 1.35,
        "momentum": 1.0,
        "structure": 1.25,
        "level": 0.35,
        "volume": 0.15,
    }
    for reading in snapshot.readings:
        weight = weights.get(reading.label, 0.0)
        if not weight:
            continue
        weighted += _bias_value(reading.bias) * weight
        weight_total += weight
    if not weight_total:
        return 0.0, 0
    return weighted / weight_total, len(snapshot.readings)


def _classify(value: float, *, strong: float = 0.30) -> str:
    if value >= strong:
        return "BULLISH"
    if value <= -strong:
        return "BEARISH"
    return "NEUTRAL"


def _momentum_state(snapshot: TechnicalSnapshot) -> str:
    histogram = snapshot.macd_histogram
    rsi = snapshot.rsi_14
    if histogram is None and rsi is None:
        return "UNDETERMINED"
    score = 0
    evidence = 0
    if histogram is not None:
        score += 1 if histogram > 0 else -1 if histogram < 0 else 0
        evidence += 1
    if rsi is not None:
        score += 1 if rsi >= 55 else -1 if rsi <= 45 else 0
        evidence += 1
    if not evidence:
        return "UNDETERMINED"
    return "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"


def _trend_state(snapshot: TechnicalSnapshot) -> str:
    if snapshot.ema_20 is None or snapshot.ema_50 is None:
        return "UNDETERMINED"
    if snapshot.ema_20 > snapshot.ema_50:
        return "BULLISH"
    if snapshot.ema_20 < snapshot.ema_50:
        return "BEARISH"
    return "NEUTRAL"


def _volatility_state(snapshot: TechnicalSnapshot) -> str:
    atr_pct = snapshot.atr_14_pct
    if atr_pct is None:
        return "UNDETERMINED"
    if atr_pct >= 2.0:
        return "HIGH"
    if atr_pct >= 0.7:
        return "NORMAL"
    return "LOW"


def _pick_primary(snapshots: dict[str, TechnicalSnapshot]) -> str:
    preferred = ("30m", "1h", "15m", "5m", "4h", "1m")
    for timeframe in preferred:
        if timeframe in snapshots:
            return timeframe
    if not snapshots:
        raise ValueError("Technical Core requires at least one non-empty timeframe")
    return sorted(snapshots)[0]


def build_technical_core_state(
    frames: dict[str, pd.DataFrame],
    *,
    market: str,
    recipe_version: str = TECHNICAL_CORE_V2_RECIPE,
) -> TechnicalCoreState:
    snapshots = build_multi_timeframe_snapshot(frames, asset=market)
    primary_timeframe = _pick_primary(snapshots)

    timeframe_weights = {"5m": 0.7, "15m": 0.9, "30m": 1.25, "1h": 1.15, "4h": 0.9}
    weighted_score = 0.0
    weight_total = 0.0
    evidence_count = 0
    for timeframe, snapshot in snapshots.items():
        score, reading_count = _snapshot_score(snapshot)
        weight = timeframe_weights.get(timeframe, 0.6)
        weighted_score += score * weight
        weight_total += weight
        evidence_count += reading_count

    score = weighted_score / weight_total if weight_total else 0.0
    coverage = min(1.0, len(snapshots) / 3.0)
    evidence = min(1.0, evidence_count / 12.0)
    agreement = min(1.0, abs(score) + 0.25)
    confidence = round(max(0.05, min(1.0, 0.45 * coverage + 0.35 * evidence + 0.20 * agreement)), 4)

    primary = snapshots[primary_timeframe]
    return TechnicalCoreState(
        market=market,
        as_of=primary.timestamp,
        recipe_version=recipe_version,
        primary_timeframe=primary_timeframe,
        trend_state=_trend_state(primary),
        momentum_state=_momentum_state(primary),
        volatility_state=_volatility_state(primary),
        structure_state=primary.market_structure,
        score=round(score, 6),
        confidence=confidence,
        snapshots={timeframe: snapshot.to_record() for timeframe, snapshot in snapshots.items()},
    )


def build_baseline_forecast(
    state: TechnicalCoreState,
    *,
    horizon_seconds: int,
) -> TechnicalBaselineForecast:
    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")

    horizon_hours = horizon_seconds / 3600.0
    direction = _classify(state.score)
    volatility_scale = {
        "LOW": 0.0035,
        "NORMAL": 0.0075,
        "HIGH": 0.014,
        "UNDETERMINED": 0.006,
    }[state.volatility_state]
    horizon_scale = max(0.35, min(2.4, horizon_hours ** 0.5))
    expected_return = state.score * volatility_scale * horizon_scale
    uncertainty = volatility_scale * horizon_scale * (1.35 - 0.55 * state.confidence)

    if direction == "NEUTRAL":
        path_shape = "MEAN_REVERTING_OR_RANGE"
    elif abs(state.score) >= 0.65:
        path_shape = "TREND_CONTINUATION"
    else:
        path_shape = "DRIFT"

    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=int(horizon_seconds),
        recipe_version=state.recipe_version,
        direction=direction,
        expected_return=round(expected_return, 8),
        lower_return=round(expected_return - uncertainty, 8),
        upper_return=round(expected_return + uncertainty, 8),
        confidence=state.confidence,
        path_shape=path_shape,
        technical_state=state,
    )
