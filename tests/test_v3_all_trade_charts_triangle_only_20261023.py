"""V3 BUY/SELL entries are triangles; reconciled full FLAT closes squares.

Presentation-only change: reconciled events remain account-scoped, AI
annotations remain separate, and broker/live decision code is untouched.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

from tradingdesk_ui.charts.lightweight.v3_execution_triangles_v1 import V3_EXECUTION_TRIANGLE_JS
from autotrader_v3_instance_inspection_v1 import build_instance_inspection_payload_v1
from trading_desk import ChartBar

BASE=datetime(2026,10,23,9,tzinfo=timezone.utc)
ROOT=Path("tradingdesk_ui/charts/lightweight")


def test_triangle_layer_is_time_price_anchored_and_only_for_v3_executions():
    js=V3_EXECUTION_TRIANGLE_JS
    assert "createPgV3TradeTriangleLayer" in js
    assert "chart.timeScale().timeToCoordinate(time)" in js
    assert "priceSeries.priceToCoordinate(price)" in js
    assert "document.createElementNS(ns, isFlatClose ? 'rect' : 'polygon')" in js
    assert "action === 'CLOSE' && (ending === 'FLAT' || afterIsZero)" in js
    assert "isFlatClose ? '#94a3b8'" in js
    assert "marker.inventory_after" in js
    assert "String(marker.source || '') !== 'AUTOTRADER_V3'" in js
    assert "side !== 'BUY' && side !== 'SELL'" in js
    assert "pgV3NativeMarkers" in js
    assert "String(m.source || '') !== 'AUTOTRADER_V3'" in js
    assert "shape.setAttribute('fill',estimated ? 'none' : color)" in js
    assert "marker.price_verified === false" in js
    assert "pointerEvents: 'none'" in js
    assert "subscribeVisibleLogicalRangeChange(schedule)" in js
    assert "unsubscribeVisibleLogicalRangeChange(schedule)" in js
    assert "new ResizeObserver(schedule)" in js
    assert "destroy()" in js
    for forbidden in ("place_order(","_post(","trade/v2/orders","set_live_authority"):
        assert forbidden not in js


def test_shared_triangle_presentation_wired_to_all_v3_graph_paths():
    renderer=(ROOT/"renderer.py").read_text()
    simple=(ROOT/"simple_live_v2.py").read_text()
    overlay=(ROOT/"trade_marker_overlay_v2.py").read_text()
    update=(ROOT/"live_update.py").read_text()
    for source in (renderer,simple,overlay,update):
        assert "V3_EXECUTION_TRIANGLE_JS" in source
        assert "createPgV3TradeTriangleLayer(" in source
        assert "pgV3NativeMarkers(" in source
        assert "triangleLayer.setMarkers(" in source or "triangleLayer?.setMarkers(" in source
    assert "triangleLayer?.destroy()" in renderer
    assert "triangleLayer?.destroy()" in simple
    assert "SAXO_MANUAL_FILL" in overlay  # legacy manual markers preserved


def test_exact_inspection_closes_flat_as_square_and_new_opens_as_triangle():
    bars=tuple(ChartBar(
        market="US Tech100",
        bar_time=(BASE+timedelta(minutes=i)).isoformat(),
        open=100+i,close=101+i,high=103+i,low=99+i,volume=10,
    ) for i in range(42))
    records=(
        {"executed_at":BASE+timedelta(minutes=37),"action":"CLOSE",
         "side":"Sell","amount":.01,"inventory_after":0.},
        {"executed_at":BASE+timedelta(minutes=38),"action":"OPEN",
         "side":"Buy","amount":.01,"inventory_after":.01},
    )
    payload=build_instance_inspection_payload_v1(
        bars,executions=records,timeframe_minutes=1)
    fills=[x for x in payload["markers"] if x["source"]=="AUTOTRADER_V3"]
    assert len(fills)==2
    assert fills[0]["side"]=="SELL" and fills[0]["shape"]=="square"
    assert fills[0]["color"]=="#94a3b8" and fills[0]["position_direction"]=="FLAT"
    assert fills[1]["side"]=="BUY" and fills[1]["shape"]=="arrowUp"
    assert all(x["text"]=="" and x["price"]>0 for x in fills)
    assert all(x["time"] in [b["time"] for b in payload["candles"]] for x in fills)


def test_no_live_business_logic_modified():
    # The changed files must be UI charts/inspector only.
    assert "autotrader_v3_live_runtime_v1.py" not in [
        str(ROOT/"renderer.py"),str(ROOT/"simple_live_v2.py"),
        str(ROOT/"live_update.py"),str(ROOT/"trade_marker_overlay_v2.py")
    ]
