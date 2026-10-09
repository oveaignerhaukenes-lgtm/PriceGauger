"""Regression coverage for TradingDesk's *active* V3 marker path.

The page renders with simple_live_v2, not the older overlay/bridge components.
"""
from datetime import datetime, timezone
from pathlib import Path

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from tradingdesk_ui.charts.lightweight.contract import _marker_payload


ROOT = Path(__file__).resolve().parents[1]


def _event(*, request: str, side: str, direction: str, account: str) -> AutoTraderTradeMarkerV1:
    return AutoTraderTradeMarkerV1(
        executed_at=datetime(2026, 10, 9, 8, 40, 15, tzinfo=timezone.utc),
        execution_price=24680.0,
        direction=direction,
        amount=0.01,
        strategy_key="i-" + account,
        net_position_id=request,
        active=False,
        source="AUTOTRADER_V3",
        action="REDUCE" if request == "r2" else ("CLOSE" if request == "r3" else "OPEN"),
        side=side,
        account_id=account,
        instance_id="i-" + account,
    )


def test_same_candle_multi_account_execution_markers_are_distinct_and_broker_sided():
    # A SELL reduction of LONG and a BUY close to FLAT must retain broker side.
    markers = (
        _event(request="r1", side="Buy", direction="LONG", account="a"),
        _event(request="r2", side="Sell", direction="LONG", account="b"),
        _event(request="r3", side="Buy", direction="FLAT", account="c"),
    )
    projected = _marker_payload(
        markers,
        candle_times=(int(datetime(2026, 10, 9, 8, 40, tzinfo=timezone.utc).timestamp()),),
        timeframe="1m",
    )
    assert len(projected) == 3
    assert len({item["id"] for item in projected}) == 3
    assert len({item["account_id"] for item in projected}) == 3
    assert {item["time"] for item in projected} == {
        int(datetime(2026, 10, 9, 8, 40, tzinfo=timezone.utc).timestamp())
    }
    assert [(item["side"], item["shape"], item["position"]) for item in projected] == [
        ("BUY", "arrowUp", "belowBar"),
        ("SELL", "arrowDown", "aboveBar"),
        ("BUY", "arrowUp", "belowBar"),
    ]
    assert all(item["marker_role"] == "EXECUTION_EVENT" for item in projected)


def test_active_simple_chart_preserves_v3_arrows_on_mount_and_tick():
    # PR #674 covered legacy overlay and updater paths, but the current page
    # actually uses simple_live_v2 for both full mount and 1s updates.
    chart = (ROOT / "tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "pages/0_TradingDesk.py").read_text(encoding="utf-8")
    passthrough = "if (String(marker.source || '') === 'AUTOTRADER_V3') return marker;"
    assert chart.count(passthrough) == 2
    assert "render_lightweight_simple_live_v2(payload" in page
    assert "isFlat ? 'square'" in chart  # Non-V3 compatibility stays intact.


def test_v3_execution_projection_limits_to_latest_events_not_oldest():
    projection = (ROOT / "autotrader_v3_trade_markers_v1.py").read_text(encoding="utf-8")
    assert "ORDER BY e.executed_at DESC, e.request_key DESC LIMIT 1000" in projection
    assert "result.sort(key=lambda marker: (marker.executed_at, marker.net_position_id))" in projection
    assert "ORDER BY e.executed_at ASC LIMIT 1000" not in projection
