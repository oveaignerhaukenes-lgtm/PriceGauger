from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from market_interpretation import STATE_NAMES
from market_state import MarketState

ASSET_WEIGHTS: dict[str, dict[str, float]] = {
    "Brent": {
        "conflict_pressure": 0.20,
        "energy_supply_risk": 0.50,
        "shipping_risk": 0.35,
        "safe_haven_pressure": 0.00,
        "usd_pressure": -0.10,
    },
    "Gold": {
        "conflict_pressure": 0.20,
        "energy_supply_risk": 0.05,
        "shipping_risk": 0.05,
        "safe_haven_pressure": 0.60,
        "usd_pressure": -0.15,
    },
    "Silver": {
        "conflict_pressure": 0.12,
        "energy_supply_risk": -0.05,
        "shipping_risk": -0.04,
        "safe_haven_pressure": 0.45,
        "usd_pressure": -0.22,
    },
    "DXY": {
        "conflict_pressure": 0.10,
        "energy_supply_risk": 0.02,
        "shipping_risk": 0.02,
        "safe_haven_pressure": 0.10,
        "usd_pressure": 0.70,
    },
}


@dataclass(frozen=True, slots=True)
class AssetRecommendation:
    asset: str
    direction: str
    score: float
    signal_strength: int
    horizon_hours: int
    rationale: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["rationale"] = list(self.rationale)
        return record


def _dot(weights: Mapping[str, float], vector: Mapping[str, float]) -> float:
    return sum(float(weights[name]) * float(vector[name]) for name in STATE_NAMES)


def build_asset_recommendation(
    asset: str,
    state: MarketState,
    *,
    level_weight: float = 0.25,
    change_weight: float = 0.75,
    dead_zone: float = 0.10,
    horizon_hours: int = 4,
) -> AssetRecommendation:
    if asset not in ASSET_WEIGHTS:
        raise ValueError(f"unsupported asset: {asset}")
    weights = ASSET_WEIGHTS[asset]
    level_score = _dot(weights, state.values)
    change_score = _dot(weights, state.change_1h)
    score = max(-1.0, min(1.0, level_weight * level_score + change_weight * change_score))
    direction = "LONG" if score > dead_zone else "SHORT" if score < -dead_zone else "NEUTRAL"
    strength = int(round(min(100.0, abs(score) * 100.0)))

    drivers = sorted(
        ((name, weights[name] * state.change_1h[name]) for name in STATE_NAMES),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    rationale = tuple(
        f"{name}: {value:+.3f}"
        for name, value in drivers[:3]
        if abs(value) >= 0.01
    )
    return AssetRecommendation(
        asset,
        direction,
        round(score, 6),
        strength,
        horizon_hours,
        rationale,
    )
