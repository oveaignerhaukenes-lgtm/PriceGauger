"""Pure V3 exposure ceiling; inputs must be verified by the LIVE caller.

No broker access, order submission or implicit currency conversion.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


@dataclass(frozen=True)
class V3ExposureCap:
    budget_nok: Decimal
    exposure_pct: Decimal
    unit_notional_nok: Decimal
    quantity_step: Decimal = Decimal("0.01")

    def __post_init__(self):
        if not (self.budget_nok > 0 and
                0 <= self.exposure_pct <= 100 and
                self.unit_notional_nok > 0 and
                self.quantity_step > 0):
            raise ValueError("invalid V3 exposure inputs")
        for value in (self.budget_nok, self.exposure_pct,
                      self.unit_notional_nok, self.quantity_step):
            if not value.is_finite():
                raise ValueError("non-finite V3 exposure input")

    @property
    def max_quantity(self) -> Decimal:
        limit = self.budget_nok * self.exposure_pct / Decimal(100)
        raw = limit / self.unit_notional_nok
        return (raw / self.quantity_step).to_integral_value(
            rounding=ROUND_DOWN) * self.quantity_step


def clamp_target_to_cap(target: Decimal, cap: V3ExposureCap) -> Decimal:
    """Cap signed target without ever increasing its absolute exposure."""
    if not target.is_finite():
        raise ValueError("non-finite target")
    magnitude = min(abs(target), cap.max_quantity)
    stepped = (magnitude / cap.quantity_step).to_integral_value(
        rounding=ROUND_DOWN) * cap.quantity_step
    return stepped.copy_sign(target) if stepped else Decimal(0)
