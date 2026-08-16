from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_shared_autotrader_only_in_right_quick_panel():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'with st.expander(f"Handel · {market}", expanded=False):' in source
    assert "AutoTraderExecutionContextV2.from_source(" in source
    assert "execution_context_v2=execution_context_v2" in source
    assert "render_saxo_product_panel(" in source
    assert "Åpne full AutoTrader" in source
    assert source.count("render_saxo_product_panel(") == 1
    assert "Hurtighandel krever eksplisitt v2-instrumentidentitet" in source

    render_index = source.index("render_saxo_product_panel(")
    chart_column_index = source.index("with chart_column:")
    assert render_index < chart_column_index
    assert not source.rstrip().endswith("render_saxo_product_panel(market)")


def test_tradingdesk_manual_execution_carries_v2_identity_without_forecast_authority():
    page_source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    panel_source = Path("trading_desk_product_panel.py").read_text(encoding="utf-8")

    assert "market_id=baseline_context.market_id" in page_source
    assert "source=baseline_context.instrument" in page_source
    assert "execution_context_v2=execution_context_v2" in page_source
    assert "execution_context_v2=execution_context_v2" in panel_source
    assert "require_v2_context=execution_context_v2 is not None" in panel_source
    assert "forecast_id" not in panel_source
    assert "render_companion_panel_v2" not in panel_source
