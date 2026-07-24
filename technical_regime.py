from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from technical_analysis import TechnicalSnapshot


@dataclass(frozen=True, slots=True)
class TechnicalRegime:
    bias: str
    signal_quality: str
    regime: str
    review_interval_minutes: int
    review_label: str
    reversal_risk: str
    rationale: tuple[str, ...]

    def to_record(self) -> dict:
        return asdict(self)


def _direction_score(snapshot: TechnicalSnapshot) -> float:
    weights = {
        "momentum": 1.0,
        "trend": 1.5,
        "structure": 1.5,
        "level": 0.5,
        "volume": 0.25,
        "volatility": 0.0,
    }
    score = 0.0
    for reading in snapshot.readings:
        weight = weights.get(reading.label, 0.5)
        if reading.bias == "bullish":
            score += weight
        elif reading.bias == "bearish":
            score -= weight
    return score


def _frame_minutes(timeframe: str) -> int:
    mapping = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    return mapping.get(timeframe.lower(), 5)


def build_technical_regime(
    snapshots: Mapping[str, TechnicalSnapshot],
) -> TechnicalRegime:
    if not snapshots:
        return TechnicalRegime(
            bias="NEUTRAL",
            signal_quality="INSUFFICIENT",
            regime="Uavklart",
            review_interval_minutes=15,
            review_label="Oppdater innen 15 minutter",
            reversal_risk="Uavklart",
            rationale=("Ingen tekniske snapshots var tilgjengelige.",),
        )

    ordered = sorted(snapshots.items(), key=lambda item: _frame_minutes(item[0]))
    scores = {timeframe: _direction_score(snapshot) for timeframe, snapshot in ordered}
    weighted_total = 0.0
    total_weight = 0.0
    for timeframe, score in scores.items():
        minutes = _frame_minutes(timeframe)
        weight = 1.0 if minutes <= 5 else 1.4 if minutes <= 30 else 1.8
        weighted_total += score * weight
        total_weight += weight
    aggregate = weighted_total / total_weight if total_weight else 0.0

    if aggregate >= 1.25:
        bias = "BULLISH"
    elif aggregate <= -1.25:
        bias = "BEARISH"
    elif aggregate >= 0.35:
        bias = "SLIGHTLY BULLISH"
    elif aggregate <= -0.35:
        bias = "SLIGHTLY BEARISH"
    else:
        bias = "NEUTRAL"

    directional = [score for score in scores.values() if abs(score) >= 0.5]
    agreement = 0.0
    if directional:
        positive = sum(score > 0 for score in directional)
        negative = sum(score < 0 for score in directional)
        agreement = max(positive, negative) / len(directional)

    nearest_level = min(
        (
            distance
            for snapshot in snapshots.values()
            for distance in (snapshot.distance_to_support_pct, snapshot.distance_to_resistance_pct)
            if distance is not None
        ),
        default=None,
    )
    max_atr = max((snapshot.atr_14_pct or 0.0 for snapshot in snapshots.values()), default=0.0)
    extreme_rsi = any(
        snapshot.rsi_14 is not None and (snapshot.rsi_14 >= 70 or snapshot.rsi_14 <= 30)
        for snapshot in snapshots.values()
    )
    conflict = len(directional) >= 2 and agreement < 0.75

    urgency = 0
    reasons: list[str] = []
    if nearest_level is not None and nearest_level <= 0.35:
        urgency += 3
        reasons.append(f"Prisen er svært nær et teknisk nivå ({nearest_level:.2f} %).")
    elif nearest_level is not None and nearest_level <= 0.8:
        urgency += 2
        reasons.append(f"Prisen er nær et teknisk nivå ({nearest_level:.2f} %).")
    if conflict:
        urgency += 3
        reasons.append("Tidsrammene peker i ulike retninger.")
    if extreme_rsi:
        urgency += 2
        reasons.append("RSI viser et ekstremområde på minst én tidsramme.")
    if max_atr >= 0.8:
        urgency += 3
        reasons.append(f"Volatiliteten er høy (maks ATR {max_atr:.2f} % av pris).")
    elif max_atr >= 0.35:
        urgency += 1
        reasons.append(f"Volatiliteten er moderat (maks ATR {max_atr:.2f} % av pris).")

    if urgency >= 7:
        interval = 5
        regime = "Svært kort og ustabilt regime"
        reversal_risk = "HØY"
    elif urgency >= 4:
        interval = 10
        regime = "Kort og skiftende regime"
        reversal_risk = "MODERAT–HØY"
    elif urgency >= 2:
        interval = 30
        regime = "Intradagregime"
        reversal_risk = "MODERAT"
    elif agreement >= 0.8 and len(directional) >= 2:
        interval = 60
        regime = "Stabilt intradagregime"
        reversal_risk = "LAV–MODERAT"
    else:
        interval = 30
        regime = "Uavklart intradagregime"
        reversal_risk = "MODERAT"

    if agreement >= 0.8 and abs(aggregate) >= 1.25 and urgency <= 1:
        signal_quality = "HIGH"
    elif agreement >= 0.65 and abs(aggregate) >= 0.5:
        signal_quality = "MEDIUM"
    elif directional:
        signal_quality = "LOW"
    else:
        signal_quality = "INSUFFICIENT"

    reasons.insert(0, f"Samlet teknisk bias: {bias}.")
    if directional:
        reasons.append(f"Retningssamsvar mellom aktive tidsrammer: {agreement * 100:.0f} %.")
    reasons.append(
        "Oppdateringsintervallet er en overvåkingsanbefaling, ikke en prognose for når markedet faktisk snur."
    )

    return TechnicalRegime(
        bias=bias,
        signal_quality=signal_quality,
        regime=regime,
        review_interval_minutes=interval,
        review_label=f"Oppdater innen {interval} minutter",
        reversal_risk=reversal_risk,
        rationale=tuple(reasons),
    )
