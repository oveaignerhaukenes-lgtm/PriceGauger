from __future__ import annotations

"""Deterministic execution core for AutoTrader V2 vNext.

This module deliberately contains no strategy logic and no portfolio-wide position
logic.  It translates one desired signed inventory on one V2-owned Saxo boundary
into at most one deterministic mutation.  Saxo exact inventory is the source of
truth; reversals close first and are re-evaluated from fresh inventory next cycle.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class V2InventoryBoundaryV1:
    account_id: str
    uic: int
    asset_type: str


@dataclass(frozen=True, slots=True)
class V2ExecutionMutationV1:
    action: str
    side: str
    amount: float
    actual_inventory: float
    desired_inventory: float
    expected_inventory: float


def _same_side(left: float, right: float) -> bool:
    return (left > EPSILON and right > EPSILON) or (left < -EPSILON and right < -EPSILON)


def _quantize_amount(amount: float, *, amount_step: float) -> float:
    step = Decimal(str(amount_step))
    if step <= 0:
        raise ValueError("amount_step must be positive")
    requested = Decimal(str(abs(float(amount))))
    units = (requested / step).to_integral_value(rounding=ROUND_DOWN)
    return float(units * step)


def plan_v2_execution_vnext_v1(
    *,
    actual_inventory: float,
    desired_inventory: float,
    amount_step: float,
) -> V2ExecutionMutationV1 | None:
    """Plan one broker mutation from exact actual inventory toward desired inventory.

    Signed inventory convention: positive=LONG, negative=SHORT, zero=FLAT.
    A reversal always closes the observed inventory first.  No OPEN is planned until
    a later cycle proves FLAT from Saxo, which removes close/open race conditions.
    """
    actual = float(actual_inventory)
    desired = float(desired_inventory)
    if abs(actual - desired) <= EPSILON:
        return None

    if abs(actual) <= EPSILON:
        raw = abs(desired)
        action = "OPEN"
        side = "Buy" if desired > 0 else "Sell"
        signed_delta = raw if side == "Buy" else -raw
    elif abs(desired) <= EPSILON:
        raw = abs(actual)
        action = "CLOSE"
        side = "Sell" if actual > 0 else "Buy"
        signed_delta = -actual
    elif not _same_side(actual, desired):
        raw = abs(actual)
        action = "CLOSE"
        side = "Sell" if actual > 0 else "Buy"
        signed_delta = -actual
    elif abs(desired) > abs(actual) + EPSILON:
        raw = abs(desired - actual)
        action = "ADD"
        side = "Buy" if actual > 0 else "Sell"
        signed_delta = raw if side == "Buy" else -raw
    else:
        raw = abs(actual - desired)
        action = "REDUCE"
        side = "Sell" if actual > 0 else "Buy"
        signed_delta = -raw if actual > 0 else raw

    amount = _quantize_amount(raw, amount_step=amount_step)
    if amount <= EPSILON:
        return None
    signed_delta = amount if side == "Buy" else -amount
    expected = actual + signed_delta
    if abs(expected) <= EPSILON:
        expected = 0.0
    return V2ExecutionMutationV1(
        action=action,
        side=side,
        amount=amount,
        actual_inventory=actual,
        desired_inventory=desired,
        expected_inventory=expected,
    )
