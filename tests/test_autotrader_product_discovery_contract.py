from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_product_discovery_keeps_broader_knockout_asset_types_and_aliases() -> None:
    source = (ROOT / "trading_desk_products.py").read_text(encoding="utf-8")

    assert '"WarrantOtherLeverageWithKnockOut"' in source
    assert '"WarrantDoubleKnockOut"' in source
    assert '"Gold": ("Gold", "XAU", "XAUUSD")' in source
    assert "by_identity" in source
