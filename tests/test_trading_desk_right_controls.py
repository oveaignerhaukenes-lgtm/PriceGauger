from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tradingdesk_keeps_page_controls_out_of_global_sidebar() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with st.sidebar" not in source
    assert "chart_column, controls_column = st.columns([4.8, 1.45]" in source
    assert "with controls_column:" in source
    assert 'with st.expander("V2 marked / analyse", expanded=True):' in source
    assert 'with st.expander("Graf", expanded=True):' in source
    assert 'with st.expander("Indikatorer", expanded=True):' in source
    assert 'with st.expander(f"Handel · {market}", expanded=False):' in source
    assert "render_saxo_product_panel(market)" in source


def test_tradingdesk_renders_v2_analysis_and_live_chart_in_main_column() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with chart_column:" in source
    assert 'analysis_fragment(run_every=f"{V2_ANALYSIS_REFRESH_SECONDS}s")(_render_v2_analysis)()' in source
    assert 'chart_fragment(run_every=f"{LIVE_CHART_REFRESH_SECONDS}s")(_render_live_chart)()' in source
    assert "render_companion_panel_v2(view)" in source
