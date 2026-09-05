from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SpringObservationV1:
    instrument_id: int
    market_id: int
    market_name: str
    observed_at: datetime
    source_window_minutes: int
    bar_count: int
    close_price: float
    equilibrium_price: float
    displacement_pct: float
    velocity_pct_per_min: float
    acceleration_pct_per_min2: float
    realized_volatility_pct: float
    range_volatility_pct: float
    shock_score: float
    energy_proxy: float
    turning_state: str
    estimated_period_minutes: float | None = None
    damping_ratio: float | None = None
    oscillation_confidence: float | None = None
    context_equilibrium_price: float | None = None
    data_quality: str = "OBSERVED"


__all__ = ["SpringObservationV1"]
