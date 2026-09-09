from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lightweight_bridge_uses_supported_directional_marker_positions() -> None:
    source = (ROOT / "tradingdesk_ui/charts/lightweight/bridge.py").read_text(encoding="utf-8")

    assert "LWC.createSeriesMarkers?.(" in source
    assert "entry.markers?.setMarkers?.(markerPayload(graph, markerTimes))" in source
    assert "position: direction === 'LONG' ? 'belowBar' : 'aboveBar'" in source
    assert "shape: direction === 'LONG' ? 'arrowUp' : 'arrowDown'" in source
    assert "position: 'atPriceMiddle'" not in source
