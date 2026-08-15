from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_product_explorer_ui_is_read_only_and_exposed_on_autotrader() -> None:
    explorer_source = (ROOT / "autotrader_product_explorer_ui.py").read_text(encoding="utf-8")
    page_source = (ROOT / "pages" / "6_AutoTrader_POC.py").read_text(encoding="utf-8")

    assert "Saxo Product Explorer" in explorer_source
    assert "IncludeNonTradable" in explorer_source
    assert "Kontokontekst" in explorer_source
    assert "Produktkategori" in explorer_source
    assert "Retning" in explorer_source
    assert "Rå Saxo-data" in explorer_source
    assert "render_saxo_product_explorer()" in page_source

    assert ".place_order(" not in explorer_source
    assert ".precheck(" not in explorer_source
    assert "execute_confirmed_manual_order" not in explorer_source
    assert "pg_v2_" not in explorer_source
    assert "INSERT " not in explorer_source.upper()
    assert "UPDATE " not in explorer_source.upper()
