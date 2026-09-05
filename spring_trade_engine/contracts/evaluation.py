from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SpringTurningPointV1:
    instrument_id: int
    observed_at: datetime
    direction: str
    close_price: float
    displacement_pct: float
    shock_score: float
    energy_proxy: float


@dataclass(frozen=True, slots=True)
class SpringEpisodeCandidateV1:
    instrument_id: int
    observed_at: datetime
    close_price: float
    displacement_pct: float
    shock_score: float
    energy_proxy: float
    trigger_rule: str


@dataclass(frozen=True, slots=True)
class SpringForwardLabelV1:
    instrument_id: int
    observed_at: datetime
    horizon_minutes: int
    realized_at: datetime
    return_pct: float
    max_up_excursion_pct: float
    max_down_excursion_pct: float


@dataclass(frozen=True, slots=True)
class SpringRuntimeCoverageV1:
    cycle_started_at: datetime
    cycle_finished_at: datetime
    active_instruments: int
    observations_persisted: int
    instruments_skipped: int
    failures: int
    forward_labels_persisted: int


__all__ = [
    "SpringEpisodeCandidateV1",
    "SpringForwardLabelV1",
    "SpringRuntimeCoverageV1",
    "SpringTurningPointV1",
]
