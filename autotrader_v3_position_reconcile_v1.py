"""Pure position-based reconciliation for one unresolved V3 broker mutation."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PositionReconciliationV3:
    state: str
    before: float
    expected: float
    actual: float
    detail: str


def reconcile_position_v3(*, expected_inventory: float, submitted_amount: float,
                          submitted_side: str, actual_inventory: float,
                          epsilon: float = 1e-9) -> PositionReconciliationV3:
    expected=float(expected_inventory); amount=abs(float(submitted_amount)); actual=float(actual_inventory)
    side=str(submitted_side or '').strip().lower()
    if amount <= epsilon or side not in {'buy','sell'}:
        raise ValueError('invalid pending V3 mutation evidence')
    signed_delta=amount if side=='buy' else -amount
    before=expected-signed_delta
    if abs(actual-expected) <= epsilon:
        return PositionReconciliationV3('CONFIRMED',before,expected,actual,'broker inventory reached expected post-order state')
    if abs(actual-before) <= epsilon:
        return PositionReconciliationV3('WAIT',before,expected,actual,'broker inventory still equals pre-order state; keep lock and never retry')
    return PositionReconciliationV3('CONFLICT',before,expected,actual,'broker inventory differs from both pre-order and expected state; external/manual mutation requires acknowledgement')
