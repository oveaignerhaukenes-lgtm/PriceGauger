from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pnl_facade_uses_lightweight_renderer_not_plotly() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_lightweight_pnl_comparison_v1" in source
    assert "load_automanager_pnl_comparison_v2(tuple(group))" in source
    assert "st.plotly_chart(" not in source
    assert "build_automanager_pnl_figure_v2" not in source


def test_lightweight_pnl_keeps_three_shared_time_panes_and_native_navigation() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_comparison.py"
    ).read_text(encoding="utf-8")
    assert "lightweight-charts@5.2.1" in source
    assert "chart.addSeries(LWC.LineSeries" in source
    assert "}, 0);" in source
    assert "}, 1);" in source
    assert "}, 2);" in source
    assert "pinch: true" in source
    assert "axisPressedMouseMove" in source
    assert "kineticScroll" in source
    assert "chart.timeScale().fitContent()" in source
    assert "setVisibleRange" in source
    assert "Plotly" not in source


def test_lightweight_pnl_legend_is_below_chart_and_modebar_is_gone() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_comparison.py"
    ).read_text(encoding="utf-8")
    root_index = source.index("shell.appendChild(root)")
    legend_index = source.index("shell.appendChild(legend)")
    assert legend_index > root_index
    assert "displayModeBar" not in source
    assert "modebar" not in source.lower()
    assert "legend.appendChild(item)" in source
    assert "api.applyOptions({{ visible: next }})" in source


def test_lightweight_pnl_preserves_live_model_and_spring_read_models() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_comparison.py"
    ).read_text(encoding="utf-8")
    assert '"live": {' in source
    assert '"models": models' in source
    assert '"spring": {' in source
    assert '"displacement"' in source
    assert '"shock"' in source
    assert '"energy"' in source
    assert "load_spring_observations_v1" in source
    assert "PAPER_SCALE_PILOT_EQUIVALENT" in source
