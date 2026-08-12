from __future__ import annotations

from trading_desk_products import LeveragedProduct


def test_placeholder_for_deterministic_order_contract() -> None:
    # Ordering itself is covered in test_trading_desk_products; this guard keeps the
    # product contract importable as discovery expands.
    assert LeveragedProduct is not None
