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
    """Read current P/L sign from an exact Saxo net position."""
    if not isinstance(row, dict):
        raise ValueError("net position must be an object")
    dynamic = row.get("NetPositionDynamic")
    if isinstance(dynamic, dict):
        for key in ("OpenProfitLoss", "ProfitLossOnTrade"):
            value = dynamic.get(key)
            if value is not None:
                return float(value)
    base = row.get("NetPositionBase") or {}
    view = row.get("NetPositionView") or {}
    opening = float(view.get("AverageOpenPriceIncludingCosts") or view.get("AverageOpenPrice") or 0.0)
    current = float(view.get("CurrentPrice") or 0.0)
    if opening <= 0.0 or current <= 0.0:
        raise ValueError("Saxo net position lacks current P/L and usable prices")
    signed = float(base.get("AmountLong") or 0.0) - float(base.get("AmountShort") or 0.0)
    if abs(signed) <= 1e-12:
        amount = abs(float(base.get("Amount") or 0.0))
        direction = str(base.get("OpeningDirection") or "").strip().lower()
        if direction == "buy":
            signed = amount
        elif direction == "sell":
            signed = -amount
    if abs(signed) <= 1e-12:
        raise ValueError("Saxo net position lacks direction")
    return (current - opening) * signed


__all__ = ["ResetOnLossModifierV3", "open_pnl_from_net_position_v3"]
