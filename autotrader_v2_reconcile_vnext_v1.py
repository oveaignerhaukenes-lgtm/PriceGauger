from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class V2ReconciliationV1:
    state: str
    detail: str


def reconcile_v2_vnext_v1(*, before_inventory: float, expected_inventory: float, actual_inventory: float, tolerance: float = 1e-8) -> V2ReconciliationV1:
    before = float(before_inventory)
    expected = float(expected_inventory)
    actual = float(actual_inventory)
    if abs(actual - expected) <= tolerance:
        return V2ReconciliationV1("CONFIRMED", "Exact Saxo inventory reached expected post-order inventory")
    if abs(actual - before) <= tolerance:
        return V2ReconciliationV1("WAIT", "Saxo inventory is still at the proven pre-submit inventory")
    return V2ReconciliationV1("CONFLICT", "Saxo inventory differs from both pre-submit and expected inventory")
