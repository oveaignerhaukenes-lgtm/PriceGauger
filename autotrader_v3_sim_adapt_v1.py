from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class SimCandidateV3:
    key: str
    score: float
    observations: int


@dataclass(frozen=True, slots=True)
class SimAdaptStateV3:
    selected_key: str | None = None
    selected_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SimAdaptPolicyV3:
    min_observations: int = 20
    switch_margin: float = 0.10
    cooldown_seconds: int = 900


@dataclass(frozen=True, slots=True)
class SimAdaptDecisionV3:
    selected_key: str | None
    switched: bool
    reason: str


def select_sim_candidate_v3(
    candidates: tuple[SimCandidateV3, ...],
    state: SimAdaptStateV3,
    *,
    policy: SimAdaptPolicyV3 = SimAdaptPolicyV3(),
    now: datetime | None = None,
) -> SimAdaptDecisionV3:
    """Select by measured SIM score with evidence, hysteresis and cooldown.

    Score construction is intentionally external: this selector must not silently
    redefine what 'better' means. It only decides whether measured superiority is
    sufficient to switch.
    """
    eligible = tuple(item for item in candidates if item.observations >= policy.min_observations)
    if not eligible:
        return SimAdaptDecisionV3(state.selected_key, False, "insufficient evidence")
    best = max(eligible, key=lambda item: item.score)
    if state.selected_key is None:
        return SimAdaptDecisionV3(best.key, True, "initial eligible leader")
    current = next((item for item in eligible if item.key == state.selected_key), None)
    if current is None:
        return SimAdaptDecisionV3(best.key, best.key != state.selected_key, "current candidate no longer eligible")
    if best.key == current.key:
        return SimAdaptDecisionV3(current.key, False, "current candidate remains leader")
    clock = now or datetime.now(timezone.utc)
    if state.selected_at is not None:
        selected_at = state.selected_at
        if selected_at.tzinfo is None:
            selected_at = selected_at.replace(tzinfo=timezone.utc)
        if (clock - selected_at).total_seconds() < policy.cooldown_seconds:
            return SimAdaptDecisionV3(current.key, False, "cooldown")
    if best.score < current.score + policy.switch_margin:
        return SimAdaptDecisionV3(current.key, False, "leader advantage below hysteresis margin")
    return SimAdaptDecisionV3(best.key, True, f"leader advantage {best.score-current.score:.3f}")
