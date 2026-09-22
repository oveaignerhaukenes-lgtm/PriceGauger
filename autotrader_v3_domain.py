from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class ControlModeV3(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    ADVISORY = "ADVISORY"
    SUPERVISOR = "SUPERVISOR"
    AUTONOMOUS = "AUTONOMOUS"
    GOD_MODE = "GOD_MODE"


@dataclass(frozen=True, slots=True)
class AccountBoundaryV3:
    account_id: str
    uic: int
    asset_type: str

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id is required")
        if int(self.uic) <= 0:
            raise ValueError("uic must be positive")
        if not self.asset_type.strip():
            raise ValueError("asset_type is required")


@dataclass(frozen=True, slots=True)
class TargetInventoryV3:
    amount: float

    def __post_init__(self) -> None:
        value = float(self.amount)
        if not isfinite(value):
            raise ValueError("target inventory must be finite")
        object.__setattr__(self, "amount", value)

    @property
    def direction(self) -> str:
        if self.amount > 0:
            return "LONG"
        if self.amount < 0:
            return "SHORT"
        return "FLAT"

    def delta_from(self, actual_amount: float) -> float:
        value = float(actual_amount)
        if not isfinite(value):
            raise ValueError("actual inventory must be finite")
        return self.amount - value


@dataclass(frozen=True, slots=True)
class CapitalAllocationV3:
    """Maximum share of the dedicated trader account available to strategy risk."""

    tradeable_pct: float = 100.0

    def __post_init__(self) -> None:
        value = float(self.tradeable_pct)
        if not isfinite(value) or value < 0.0 or value > 100.0:
            raise ValueError("tradeable_pct must be between 0 and 100")
        object.__setattr__(self, "tradeable_pct", value)

    @property
    def fraction(self) -> float:
        return self.tradeable_pct / 100.0

    def tradeable_equity(self, account_equity: float) -> float:
        equity = float(account_equity)
        if not isfinite(equity) or equity < 0.0:
            raise ValueError("account_equity must be finite and non-negative")
        return equity * self.fraction


@dataclass(frozen=True, slots=True)
class DecisionSnapshotV3:
    trader_id: str
    account: AccountBoundaryV3
    mode: ControlModeV3
    strategy_key: str
    capital_allocation: CapitalAllocationV3
    base_target: TargetInventoryV3
    effective_target: TargetInventoryV3
    risk_approved_target: TargetInventoryV3
    actual_inventory: TargetInventoryV3
    pending_delta: float

    def __post_init__(self) -> None:
        expected = self.risk_approved_target.delta_from(self.actual_inventory.amount)
        if abs(float(self.pending_delta) - expected) > 1e-9:
            raise ValueError("pending_delta must equal risk-approved target minus actual inventory")


def signed_inventory_v3(*, direction: str, amount: float) -> TargetInventoryV3:
    qty = abs(float(amount))
    normalized = str(direction or "").strip().upper()
    if normalized in {"BUY", "LONG"}:
        return TargetInventoryV3(qty)
    if normalized in {"SELL", "SHORT"}:
        return TargetInventoryV3(-qty)
    if normalized == "FLAT":
        return TargetInventoryV3(0.0)
    raise ValueError(f"unsupported inventory direction: {direction}")


__all__ = [
    "AccountBoundaryV3",
    "CapitalAllocationV3",
    "ControlModeV3",
    "DecisionSnapshotV3",
    "TargetInventoryV3",
    "signed_inventory_v3",
]
