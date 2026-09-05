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
    guard = "if (!pointerInsidePlot(graph, event.clientX, event.clientY)) return;"
    assert guard in source
    assert source.index(guard) < source.index("event.preventDefault();", source.index("const onWheel"))


def test_vertical_trackpad_motion_scales_price_y_axis_instead_of_panning() -> None:
    source = Path("trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")
    assert "ratioFromBottom" in source
    assert "const anchor = start + span * ratioFromBottom;" in source
    assert "const nextStart = anchor + (start - anchor) * factor;" in source
    assert "const nextEnd = anchor + (end - anchor) * factor;" in source
    assert "'yaxis.range': [nextStart, nextEnd]" in source


def test_autotrader_trade_triangles_are_compact_and_text_free() -> None:
    source = Path("trading_desk_live_overlay_v2.py").read_text(encoding="utf-8")
    assert "const radius = active ? 4 : 3;" in source
    assert "context.lineWidth = active ? 1.2 : 0.8;" in source
    assert "context.fillText" not in source
    assert "AKTIV ${direction}" not in source
