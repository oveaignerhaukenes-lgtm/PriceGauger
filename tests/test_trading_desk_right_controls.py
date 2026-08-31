from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tradingdesk_keeps_page_controls_out_of_global_sidebar_and_automanager_out_of_controls_column() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with st.sidebar" not in source
    assert "chart_column, controls_column = st.columns([4.8, 1.45]" in source
    assert "with controls_column:" in source
    assert 'with st.expander("V2 marked / analyse", expanded=True):' in source
    assert 'with st.expander("Graf", expanded=True):' in source
    assert 'with st.expander("Indikatorer", expanded=True):' in source
    assert 'with st.expander("Status", expanded=False):' in source
    assert 'with st.expander(f"Handel · {market}"' not in source
    assert 'with st.expander(f"AutoManage · {market}"' not in source
    assert "def _render_automanager_workspace()" in source
    assert "render_tradingdesk_automanage_panel_v2(context)" in source


def test_tradingdesk_renders_v2_analysis_live_chart_and_automanager_in_main_column() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with chart_column:" in source
    assert "if auto_refresh:" in source
    assert 'analysis_fragment(run_every=f"{V2_ANALYSIS_REFRESH_SECONDS}s")(_render_v2_analysis_snapshot)()' in source
    assert 'chart_fragment(run_every=f"{LIVE_CHART_BASE_REFRESH_SECONDS}s")(_render_live_chart)()' in source
    assert 'overlay_fragment(run_every=f"{LIVE_CANDLE_OVERLAY_REFRESH_SECONDS}s")(_render_live_candle_overlay)()' in source
    assert "else:\n        _render_v2_analysis()\n        _render_live_chart_controls()\n        _render_live_chart()" in source
    assert "render_companion_panel_v2(view)" in source
    assert "_render_automanager_workspace()" in source
    assert source.index("with chart_column:") < source.rindex("_render_automanager_workspace()")


def test_tradingdesk_auto_refresh_is_default_and_fragment_scoped() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'AUTO_REFRESH_STATE_KEY = "tradingdesk_auto_refresh"' in source
    assert "st.session_state[AUTO_REFRESH_STATE_KEY] = True" in source
    assert '"Autooppdater TradingDesk"' in source
    assert "LIVE_CHART_BASE_REFRESH_SECONDS = 60" in source
    assert "LIVE_CANDLE_OVERLAY_REFRESH_SECONDS = 1" in source
    assert "V2_ANALYSIS_REFRESH_SECONDS = 60" in source


def test_timed_fragments_do_not_recreate_interactive_controls() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    companion_source = (ROOT / "companion_ui_v2.py").read_text(encoding="utf-8")

    assert "_render_v2_analysis(include_companion=False)" in source
    assert "_render_companion_workspace()\n\n        _render_live_chart_controls()" in source
    live_chart_body = source.split("def _render_live_chart() -> None:", 1)[1].split(
        "def _render_automanager_workspace()", 1
    )[0]
    assert "st.popover(" not in live_chart_body
    assert 'width="stretch"' in live_chart_body
    assert "value=st.session_state[MODE_KEY]" not in companion_source


def test_second_updates_use_browser_overlay_instead_of_replacing_plotly_chart() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")

    assert "render_live_candle_overlay_v2(" in source
    assert "parse_live_chart_view_v2(st.session_state.get(navigation_key))" in source
    assert "fig.update_xaxes(range=list(saved_view.x_range), autorange=False)" in source
    assert "fig.update_yaxes(range=list(saved_view.y_range), autorange=False" in source
    assert source.count('run_every=f"{LIVE_CANDLE_OVERLAY_REFRESH_SECONDS}s"') == 1
    assert source.count('run_every=f"{LIVE_CHART_BASE_REFRESH_SECONDS}s"') == 1
