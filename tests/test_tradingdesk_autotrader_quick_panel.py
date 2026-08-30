from __future__ import annotations

from pathlib import Path


def test_tradingdesk_uses_main_automanager_instead_of_manual_autotrader_quick_panel():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'with st.expander(f"Handel · {market}"' not in source
    assert "render_saxo_product_panel(" not in source
    assert "AutoTraderExecutionContextV2.from_source(" not in source
    assert "def _render_automanager_workspace()" in source
    assert "render_tradingdesk_automanage_panel_v2(context)" in source
    assert 'st.page_link("pages/6_AutoTrader_POC.py", label="Full AutoTrader"' in source


def test_retained_manual_execution_component_still_requires_v2_identity_if_reused_elsewhere():
    panel_source = Path("trading_desk_product_panel.py").read_text(encoding="utf-8")
    execution_source = Path("autotrader_manual_execution.py").read_text(encoding="utf-8")

    assert "execution_context_v2=execution_context_v2" in panel_source
    assert "require_v2_context=execution_context_v2 is not None" in panel_source
    assert "verify_execution_context_v2(intent.execution_context_v2)" in execution_source
    assert "forecast_id" not in panel_source
    assert "render_companion_panel_v2" not in panel_source
