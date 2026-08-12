from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_shared_autotrader_only_in_sidebar_quick_panel():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'with st.expander(f"AutoTrader · hurtighandel · {market}", expanded=False):' in source
    assert "render_saxo_product_panel(market)" in source
    assert "Åpne full AutoTrader" in source
    assert source.count("render_saxo_product_panel(market)") == 1

    render_index = source.index("render_saxo_product_panel(market)")
    fragment_index = source.index('_fragment = getattr(st, "fragment"')
    assert render_index < fragment_index
    assert not source.rstrip().endswith("render_saxo_product_panel(market)")
