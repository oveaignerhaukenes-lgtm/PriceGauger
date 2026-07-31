from __future__ import annotations

import math


ASSET_COLORS: dict[str, str] = {
    "Brent": "#171717",
    "Gold": "#d88716",
    "Silver": "#8c96a0",
    "Natural Gas": "#168f8a",
    "DXY": "#244a7c",
}


def asset_color(market: str) -> str:
    """Return a stable instrument identity color for the overview UI."""
    return ASSET_COLORS.get(str(market), "#6f7780")


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
