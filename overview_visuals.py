from __future__ import annotations

import math


ASSET_COLORS: dict[str, str] = {
    # Identity colors must remain readable on PriceGauger's dark surfaces.
    "Brent": "#d6a04a",
    "Gold": "#d88716",
    "Silver": "#8c96a0",
    "Natural Gas": "#168f8a",
    "DXY": "#3f6fa8",
}


def asset_color(market: str) -> str:
    """Return a stable, dark-surface-safe instrument identity color."""
    return ASSET_COLORS.get(str(market), "#8b95a1")


def visual_direction_score(raw_score: float) -> float:
    """Map an uncalibrated directional score to a non-saturating display scale.

    This is deliberately only a presentation transform. The raw Decision State
    remains visible and confidence is rendered separately. A raw score of ±1.0
    therefore no longer fills the entire gauge before statistical calibration is
    available.
    """
    return max(-1.0, min(1.0, math.tanh(float(raw_score) * 0.75)))


def bipolar_fill(raw_score: float) -> tuple[float, float, float]:
    """Return left width, right width and marker position as percentages."""
    score = visual_direction_score(raw_score)
    left = abs(min(0.0, score)) * 50.0
    right = max(0.0, score) * 50.0
    marker = 50.0 + score * 50.0
    return left, right, marker
