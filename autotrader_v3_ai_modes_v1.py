from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_registry_v1 import MODIFIERS_V3, STRATEGIES_V3, TIMEFRAMES_V3


@dataclass(frozen=True, slots=True)
class OverseerDecisionV3:
    strategy_key: str
    timeframe: str
    modifiers: tuple[str, ...]
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if self.strategy_key not in {item.key for item in STRATEGIES_V3}:
            raise ValueError("Overseer selected unknown strategy")
        if self.timeframe not in TIMEFRAMES_V3:
            raise ValueError("Overseer selected unknown timeframe")
        if set(self.modifiers) - {item.key for item in MODIFIERS_V3}:
            raise ValueError("Overseer selected unknown modifier")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0,1]")


@dataclass(frozen=True, slots=True)
class GodModeDecisionV3:
    target: TargetInventoryV3
    confidence: float
    reason: str
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0,1]")
        if not self.reason.strip():
            raise ValueError("God Mode decision requires an auditable reason")


def god_mode_target_v3(decision: GodModeDecisionV3, *, now: datetime) -> TargetInventoryV3:
    """Return AI target only while valid.

    This function deliberately cannot create Saxo orders. The returned target must
    still pass the normal V3 Risk Governor and hardened Execution boundary.
    """
    if decision.valid_until is not None:
        until = decision.valid_until
        current = now
        if until.tzinfo is None and current.tzinfo is not None:
            until = until.replace(tzinfo=current.tzinfo)
        if current > until:
            return TargetInventoryV3(0.0)
    return decision.target
