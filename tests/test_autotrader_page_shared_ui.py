from pathlib import Path


def test_autotrader_page_uses_canonical_v2_automanager_not_legacy_manual_sim_panel():
    source = Path("pages/6_AutoTrader_POC.py").read_text(encoding="utf-8")

    assert "load_trading_desk_contexts_v2" in source
    assert "render_tradingdesk_automanage_panel_v2(context)" in source
    assert "render_saxo_product_panel" not in source
    assert "MARKET_SEARCH_TERMS" not in source
    assert "SaxoOrderRequest" not in source
    assert ".place_order(" not in source
    assert ".precheck(" not in source
    assert "proof of concept" not in source.lower()
