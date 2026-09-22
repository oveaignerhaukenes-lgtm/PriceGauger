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
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdTrailingDecisionV3:
    """Move desired inventory one tranche toward current MACD evidence.

    This is intentionally a pure strategy function: no Saxo observation, persistence,
    capital lookup or order path. Repeated closed observations can accumulate inventory
    up to max_inventory; a sign reversal first walks inventory back through zero.
    """
    spread = float(observation.spread)
    current = _quantize(current_target.amount, config.tranche)
    if abs(spread) <= config.deadband:
        return MacdTrailingDecisionV3(
            target=TargetInventoryV3(current),
            action="HOLD",
            reason=f"MACD spread {spread:+.6f} inside deadband",
            spread=spread,
        )

    direction = 1.0 if spread > 0 else -1.0
    proposed = current + direction * config.tranche
    bounded = max(-config.max_inventory, min(config.max_inventory, proposed))
    bounded = _quantize(bounded, config.tranche)
    if bounded == current:
        action = "HOLD_MAX"
    elif abs(bounded) < abs(current):
        action = "REDUCE"
    elif current == 0 or (current > 0) == (bounded > 0):
        action = "ADD"
    else:
        action = "CROSS_ZERO"

    return MacdTrailingDecisionV3(
        target=TargetInventoryV3(bounded),
        action=action,
        reason=f"MACD spread {spread:+.6f}; one {config.tranche:g} tranche toward evidence",
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
    for observation in observations:
        decision = macd_trailing_target_v3(
            current_target=target,
            observation=observation,
            config=config,
        )
        decisions.append(decision)
        target = decision.target
    return tuple(decisions)


__all__ = [
    "STRATEGY_KEY_V3",
    "MacdTrailingConfigV3",
    "MacdTrailingDecisionV3",
    "macd_trailing_target_v3",
    "replay_macd_trailing_targets_v3",
]
