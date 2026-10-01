from __future__ import annotations

from dataclasses import dataclass

from autotrader_v3_domain import TargetInventoryV3


@dataclass(frozen=True, slots=True)
class ResetOnLossModifierV3:
    """Flatten an existing position whenever its current open P/L is negative.

    This is deliberately direction-agnostic and has no reversal authority.
    Once flat, the strategy is free to rebuild from its normal first tranche.
    """
    open_pnl: float
    actual_inventory: float
    key: str = "reset-on-loss"

    def apply(self, trader, target: TargetInventoryV3):
        if abs(float(self.actual_inventory)) <= 1e-12:
            return target, "flat inventory; reset-on-loss inactive"
        if float(self.open_pnl) < 0.0:
            return TargetInventoryV3(0.0), (
                f"open P/L {float(self.open_pnl):.6g} < 0; reset target to FLAT"
            )
        return target, f"open P/L {float(self.open_pnl):.6g} >= 0; pass-through"


def open_pnl_from_net_position_v3(row: dict) -> float:
    """Read Saxo's current open P/L from an exact account/product net position."""
    if not isinstance(row, dict):
        raise ValueError("net position must be an object")
    dynamic = row.get("NetPositionDynamic")
    if not isinstance(dynamic, dict):
        raise ValueError("Saxo net position lacks NetPositionDynamic")
    for key in ("OpenProfitLoss", "ProfitLossOnTrade", "PositionValue"):
        value = dynamic.get(key)
        if key != "PositionValue" and value is not None:
            return float(value)
    raise ValueError("Saxo net position lacks current open P/L")


__all__ = ["ResetOnLossModifierV3", "open_pnl_from_net_position_v3"]
