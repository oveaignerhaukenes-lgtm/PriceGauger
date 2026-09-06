from __future__ import annotations

from pathlib import Path


def test_hover_updates_cursor_inspector_and_linked_crosshair() -> None:
    source = Path("trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")
    assert "renderInspectorsAtX(xValue);" in source
    assert "showLinkedCrosshairs" in source
    assert "pg-linked-crosshair" in source
    assert "pg-chart-inspector" in source
    assert "for (const graph of enhanced.keys())" in source


def test_live_wheel_is_captured_only_inside_plot_rectangle() -> None:
    source = Path("trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")
    wheel = source.split("const onWheel = (event) => {", 1)[1].split("};", 1)[0]
    assert "pointerInsidePlot(graph, event.clientX, event.clientY)" in wheel
    assert wheel.index("pointerInsidePlot") < wheel.index("event.preventDefault();")
    assert "event.stopImmediatePropagation();" in wheel


def test_vertical_trackpad_motion_scales_actual_candlestick_price_axis() -> None:
    source = Path("trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")
    assert "function priceYAxis" in source
    assert "axisKeyFromTraceRef(candle?.yaxis || 'y')" in source
    assert "ratioFromBottom" in source
    assert "function relayoutYScale" in source
    assert "[`${target.key}.range`]" in source
    assert "relayoutYScale(graph, priceYAxis(graph)" in source


def test_autotrader_trade_triangles_are_compact_and_text_free() -> None:
    source = Path("trading_desk_live_overlay_v2.py").read_text(encoding="utf-8")
    assert "const radius = active ? 4 : 3;" in source
    assert "context.lineWidth = active ? 1.2 : 0.8;" in source
    assert "context.fillText" not in source
    assert "AKTIV ${direction}" not in source
