"""Histogram Peak Flip V3: one-tranche, closed-bar, peak-gated reversals.

Research SIM-only. Does not import Saxo, database, accounts or live authority.

NEGATIVE histogram starts rising -> LONG; a renewed negative push -> SHORT
until a fully closed histogram exceeds the previously recorded recovery PEAK.
POSITIVE histogram starts falling -> SHORT; renewed positive push -> LONG
until a fully closed histogram falls below the preceding cooling TROUGH.

The threshold is frozen on the opposite push, rather than moving during
counter-trend consolidation. Strict break (> or <) avoids equality churn.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal, Sequence

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3, MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "macd-histogram-peak-flip-v1"
Phase = Literal["WAIT", "NEG_RECOVERY", "NEG_PUSH", "POS_COOLING", "POS_PUSH"]


@dataclass(frozen=True, slots=True)
class HistogramPeakStateV3:
    phase: Phase = "WAIT"
    reference: float | None = None

    def __post_init__(self):
        if self.phase not in {"WAIT", "NEG_RECOVERY", "NEG_PUSH", "POS_COOLING", "POS_PUSH"}:
            raise ValueError("unsupported histogram peak phase")
        if self.phase == "WAIT":
            if self.reference is not None:
                raise ValueError("WAIT must not retain old extrema")
        elif self.reference is None or not isfinite(self.reference):
            raise ValueError("active histogram phase requires a finite peak/trough")


@dataclass(frozen=True, slots=True)
class HistogramPeakTransitionV3:
    decision: MacdHistogramDecisionV3
    state: HistogramPeakStateV3


def histogram_peak_flip_transition_v3(
    *, current_target: TargetInventoryV3, observation: MacdObservationV2,
    previous_observation: MacdObservationV2 | None,
    state: HistogramPeakStateV3 = HistogramPeakStateV3(),
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> HistogramPeakTransitionV3:
    """Consume exactly one closed histogram observation and previous persisted phase.

    Signal and reference are deterministic; current_target is never used to
    infer an unpersisted extrema. The caller serializes state with the normal
    closed-bar cursor. New/changed strategies start in WAIT.
    """
    h = float(observation.spread)
    if not isfinite(h):
        raise ValueError("histogram must be finite")
    current = float(current_target.amount)
    if previous_observation is None:
        decision = MacdHistogramDecisionV3(
            current_target, "HOLD_BOOTSTRAP",
            "No previous closed histogram: await a true negative recovery or positive cooling",
            h)
        return HistogramPeakTransitionV3(decision, HistogramPeakStateV3())

    prev = float(previous_observation.spread)
    if not isfinite(prev):
        raise ValueError("previous histogram must be finite")

    phase = state.phase
    next_state = state
    intended: int | None = None  # -1 short, +1 long, None means keep current target
    event = "HOLD"
    detail = "No peak/trough breakout"

    if phase == "WAIT":
        if prev < 0 and h > prev:
            next_state = HistogramPeakStateV3("NEG_RECOVERY", h)
            intended, event = 1, "NEGATIVE_RECOVERY_LONG"
            detail = f"negative histogram recovers {prev:+.6f}->{h:+.6f}"
        elif prev > 0 and h < prev:
            next_state = HistogramPeakStateV3("POS_COOLING", h)
            intended, event = -1, "POSITIVE_COOLING_SHORT"
            detail = f"positive histogram cools {prev:+.6f}->{h:+.6f}"

    elif phase == "NEG_RECOVERY":
        # Changing from a negative recovery to positive cooling is a NEW
        # primary setup, not a push against the old negative-regime level.
        if h > 0 and h < prev:
            next_state = HistogramPeakStateV3("POS_COOLING", h)
            intended, event = -1, "POSITIVE_COOLING_SHORT"
            detail = f"positive histogram cools {prev:+.6f}->{h:+.6f}"
        elif h < 0 and h < prev:
            peak = max(float(state.reference), prev)
            next_state = HistogramPeakStateV3("NEG_PUSH", peak)
            intended, event = -1, "RENEWED_NEGATIVE_PUSH_SHORT"
            detail = f"negative push resumes; freeze recovery peak at {peak:+.6f}"
        else:
            next_state = HistogramPeakStateV3("NEG_RECOVERY", max(float(state.reference), h))
            detail = f"recovery peak now {next_state.reference:+.6f}"

    elif phase == "NEG_PUSH":
        peak = float(state.reference)
        if h > peak:
            next_state = HistogramPeakStateV3("NEG_RECOVERY", h)
            intended, event = 1, "BREAK_PREVIOUS_PEAK_LONG"
            detail = f"histogram {h:+.6f} exceeds frozen recovery peak {peak:+.6f}"
        else:
            detail = f"hold counter SHORT until histogram > {peak:+.6f}"

    elif phase == "POS_COOLING":
        if h < 0 and h > prev:
            next_state = HistogramPeakStateV3("NEG_RECOVERY", h)
            intended, event = 1, "NEGATIVE_RECOVERY_LONG"
            detail = f"negative histogram recovers {prev:+.6f}->{h:+.6f}"
        elif h > 0 and h > prev:
            trough = min(float(state.reference), prev)
            next_state = HistogramPeakStateV3("POS_PUSH", trough)
            intended, event = 1, "RENEWED_POSITIVE_PUSH_LONG"
            detail = f"positive push resumes; freeze cooling trough at {trough:+.6f}"
        else:
            next_state = HistogramPeakStateV3("POS_COOLING", min(float(state.reference), h))
            detail = f"cooling trough now {next_state.reference:+.6f}"

    elif phase == "POS_PUSH":
        trough = float(state.reference)
        if h < trough:
            next_state = HistogramPeakStateV3("POS_COOLING", h)
            intended, event = -1, "BREAK_PREVIOUS_TROUGH_SHORT"
            detail = f"histogram {h:+.6f} falls below frozen cooling trough {trough:+.6f}"
        else:
            detail = f"hold counter LONG until histogram < {trough:+.6f}"

    target = current_target if intended is None else TargetInventoryV3(
        config.tranche * intended)
    if abs(target.amount) > config.max_inventory + 1e-9:
        raise ValueError("peak-flip target exceeds instrument inventory cap")
    if intended is None or abs(target.amount - current) < 1e-9:
        action = "HOLD"
    elif current == 0:
        action = "OPEN"
    elif current * target.amount < 0:
        action = "FLIP"
    else:
        action = "TARGET_ONE_TRANCHE"

    # Keep a semantic event separate from the operational action, so UI
    # auditing explains WHY the desired position changed.
    reason = f"{event}: {detail}; phase={next_state.phase}"
    decision = MacdHistogramDecisionV3(target, action, reason, h)
    return HistogramPeakTransitionV3(decision, next_state)


def replay_histogram_peak_flip_v3(
    observations: Sequence[MacdObservationV2], *,
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
    initial_target: TargetInventoryV3 = TargetInventoryV3(0),
) -> tuple[HistogramPeakTransitionV3, ...]:
    """Pure chronological replay (signals only; no assumed trade fills)."""
    previous = None
    state = HistogramPeakStateV3()
    target = initial_target
    outputs = []
    for observation in observations:
        outcome = histogram_peak_flip_transition_v3(
            current_target=target, observation=observation,
            previous_observation=previous, state=state, config=config)
        outputs.append(outcome)
        target, state, previous = outcome.decision.target, outcome.state, observation
    return tuple(outputs)


__all__ = [
    "STRATEGY_KEY_V3", "HistogramPeakStateV3",
    "HistogramPeakTransitionV3", "histogram_peak_flip_transition_v3",
    "replay_histogram_peak_flip_v3",
]
