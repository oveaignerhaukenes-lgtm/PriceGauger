from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3


STRATEGY_KEY_V3 = "macd-trailing-v1"


@dataclass(frozen=True, slots=True)
class MacdTrailingConfigV3:
    tranche: float = 0.01
    max_inventory: float = 0.10
    deadband: float = 0.0

    def __post_init__(self) -> None:
        tranche = float(self.tranche)
        maximum = float(self.max_inventory)
        deadband = float(self.deadband)
        if not isfinite(tranche) or tranche <= 0:
            raise ValueError("tranche must be finite and positive")
        if not isfinite(maximum) or maximum < tranche:
            raise ValueError("max_inventory must be at least one tranche")
        if not isfinite(deadband) or deadband < 0:
            raise ValueError("deadband must be finite and non-negative")
        object.__setattr__(self, "tranche", tranche)
        object.__setattr__(self, "max_inventory", maximum)
        object.__setattr__(self, "deadband", deadband)


@dataclass(frozen=True, slots=True)
class MacdTrailingDecisionV3:
    target: TargetInventoryV3
    action: str
    reason: str
    spread: float


def _quantize(value: float, tranche: float) -> float:
    steps = round(value / tranche)
    result = steps * tranche
    return 0.0 if abs(result) < tranche / 2 else result


def macd_trailing_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation: MacdObservationV2,
    previous_observation: MacdObservationV2 | None = None,
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdTrailingDecisionV3:
    """Trail exposure inside the active MACD regime.

    MACD spread sign owns direction:
    - bullish spread permits LONG exposure only;
    - bearish spread permits SHORT exposure only;
    - any existing opposite-side target is flattened immediately on the first
      closed observation in the new regime.

    MACD impulse controls tranche-by-tranche sizing *inside* that regime. A
    weakening impulse may trail exposure back toward zero, but it may never
    rebuild on the wrong side of the current MACD regime.
    """
    spread = float(observation.spread)
    current = _quantize(current_target.amount, config.tranche)

    if spread > config.deadband:
        regime = 1
    elif spread < -config.deadband:
        regime = -1
    else:
        regime = 0

    # Regime ownership is absolute: never carry an opposite-side target across
    # a completed MACD cross. This also safely closes legacy inventory when the
    # first post-deploy observation is already on the opposite side.
    if current > 0.0 and regime < 0:
        return MacdTrailingDecisionV3(
            target=TargetInventoryV3(0.0),
            action="REGIME_CROSS_FLAT",
            reason=f"bearish MACD regime spread {spread:+.6f}; flatten entire LONG target",
            spread=spread,
        )
    if current < 0.0 and regime > 0:
        return MacdTrailingDecisionV3(
            target=TargetInventoryV3(0.0),
            action="REGIME_CROSS_FLAT",
            reason=f"bullish MACD regime spread {spread:+.6f}; flatten entire SHORT target",
            spread=spread,
        )

    if regime == 0:
        return MacdTrailingDecisionV3(
            target=TargetInventoryV3(current),
            action="HOLD",
            reason=f"MACD spread {spread:+.6f} inside deadband",
            spread=spread,
        )

    previous_spread = float(previous_observation.spread) if previous_observation is not None else None
    if previous_spread is None:
        delta = config.tranche * regime
        evidence = "initial regime"
    else:
        impulse = spread - previous_spread
        if abs(impulse) <= config.deadband:
            delta = 0.0
            evidence = "flat impulse"
        elif regime > 0:
            if impulse > 0:
                delta = config.tranche
                evidence = f"bullish impulse {impulse:+.6f}"
            elif current > 0:
                delta = -config.tranche
                evidence = f"weakening bullish regime {impulse:+.6f}"
            else:
                delta = 0.0
                evidence = f"bullish regime but weakening impulse {impulse:+.6f}"
        else:
            if impulse < 0:
                delta = -config.tranche
                evidence = f"bearish impulse {impulse:+.6f}"
            elif current < 0:
                delta = config.tranche
                evidence = f"weakening bearish regime {impulse:+.6f}"
            else:
                delta = 0.0
                evidence = f"bearish regime but weakening impulse {impulse:+.6f}"

    proposed = current + delta
    # The active MACD regime is a hard directional boundary. Impulse may reduce
    # exposure to zero, but it cannot cross through zero into the wrong side.
    if regime > 0:
        proposed = max(0.0, proposed)
    else:
        proposed = min(0.0, proposed)

    bounded = max(-config.max_inventory, min(config.max_inventory, proposed))
    bounded = _quantize(bounded, config.tranche)
    if bounded == current:
        action = "HOLD_MAX" if abs(current) >= config.max_inventory else "HOLD_IMPULSE"
    elif abs(bounded) < abs(current):
        action = "TRAIL_OUT"
    else:
        action = "ADD_IMPULSE"

    return MacdTrailingDecisionV3(
        target=TargetInventoryV3(bounded),
        action=action,
        reason=f"MACD spread {spread:+.6f}; {evidence}; one {config.tranche:g} tranche",
        spread=spread,
    )

def replay_macd_trailing_targets_v3(
    observations: Sequence[MacdObservationV2],
    *,
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
    initial_target: TargetInventoryV3 = TargetInventoryV3(0.0),
) -> tuple[MacdTrailingDecisionV3, ...]:
    decisions: list[MacdTrailingDecisionV3] = []
    target = initial_target
    previous = None
    for observation in observations:
        decision = macd_trailing_target_v3(
            current_target=target,
            observation=observation,
            previous_observation=previous,
            config=config,
        )
        decisions.append(decision)
        target = decision.target
        previous = observation
    return tuple(decisions)


__all__ = [
    "STRATEGY_KEY_V3",
    "MacdTrailingConfigV3",
    "MacdTrailingDecisionV3",
    "macd_trailing_target_v3",
    "replay_macd_trailing_targets_v3",
]
