from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legend_hover_highlights_target_and_restores_other_series() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")

    assert "pointerover" in source
    assert "pointerout" in source
    assert "window.Plotly" in source
    assert "plotly.restyle" in source
    assert "Math.min(0.14, value)" in source
    assert "restore()" in source


def test_legend_hover_component_is_rendered_with_stable_chart_controls() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    controls = source.split("def _render_live_chart_controls() -> None:", 1)[1].split(
        "def _live_chart_uirevision()", 1
    )[0]
    live_chart = source.split("def _render_live_chart() -> None:", 1)[1].split(
        "def _render_automanager_workspace()", 1
    )[0]

    assert "render_trading_desk_legend_hover_v1" in controls
    assert "render_trading_desk_legend_hover_v1" not in live_chart
