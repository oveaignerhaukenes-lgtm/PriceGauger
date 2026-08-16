from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_shared_autotrader_only_in_right_quick_panel():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'with st.expander(f"Handel · {market}", expanded=False):' in source
    assert "render_saxo_product_panel(market)" in source
    assert "Åpne full AutoTrader" in source
    assert source.count("render_saxo_product_panel(market)") == 1
    assert "Hurtighandel krever eksplisitt v2-instrumentidentitet" in source

    render_index = source.index("render_saxo_product_panel(market)")
    chart_column_index = source.index("with chart_column:")
    assert render_index < chart_column_index
    assert not source.rstrip().endswith("render_saxo_product_panel(market)")
