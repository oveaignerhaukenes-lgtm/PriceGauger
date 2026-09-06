from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pnl_facade_uses_strategy_lab_lightweight_renderer_not_plotly() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "render_strategy_lab_pnl_v1" in source
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


def test_strategy_lab_splits_controls_from_advanced_models() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab.py"
    ).read_text(encoding="utf-8")
    assert "baseline_models" in source
    assert "advanced_models" in source
    assert "MACD_CONTROL_STRATEGY_KEYS_V1" in source
    assert "SHADOW_CONTROL" not in source  # classification stays on persisted identity/labels, not new execution semantics
    assert "strategy_key in _CONTROL_KEYS" in source
    assert "label.startswith(\"Control ·\")" in source


def test_strategy_lab_adds_market_regime_reference_from_canonical_bars() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab.py"
    ).read_text(encoding="utf-8")
    assert "CanonicalMarketBarStoreV2" in source
    assert "load_instrument_range" in source
    assert '"label": "Marked · % fra start"' in source
    assert "((float(bar.close) / anchor) - 1.0) * 100.0" in source


def test_strategy_lab_spring_energy_is_visible_by_default() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab.py"
    ).read_text(encoding="utf-8")
    assert "Spring · energy proxy" in source
    assert "visible: true" in source
    assert "addLegend(energy, 'Spring · energy proxy', '#f59e0b', true)" in source


def test_strategy_lab_keeps_native_lightweight_navigation_and_two_charts() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab.py"
    ).read_text(encoding="utf-8")
    assert "pinch: true" in source
    assert "axisPressedMouseMove" in source
    assert "kineticScroll" in source
    assert "mode === 'baseline'" in source
    assert 'data={"payload": payload, "mode": "baseline"}' in source
    assert 'data={"payload": payload, "mode": "advanced"}' in source
    assert "Plotly" not in source
