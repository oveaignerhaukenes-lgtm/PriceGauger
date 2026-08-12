from pathlib import Path


def test_autotrader_page_reuses_shared_product_execution_panel():
    source = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")

    assert "render_saxo_product_panel" in source
    assert "MARKET_SEARCH_TERMS" in source
    assert "SaxoOrderRequest" not in source
    assert ".place_order(" not in source
    assert ".precheck(" not in source
    assert "Antall" not in source
    assert "proof of concept" not in source.lower()
