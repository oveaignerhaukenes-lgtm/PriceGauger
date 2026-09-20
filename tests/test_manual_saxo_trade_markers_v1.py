from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from manual_saxo_trade_markers_v1 import parse_manual_fill_v1
from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED
from tradingdesk_ui.charts.lightweight.contract import build_lightweight_live_payload_v1


ROOT = Path(__file__).resolve().parents[1]


def _activity(**changes):
    row = {
        "AccountId": "ACC-1",
        "ActivityTime": "2026-09-20T22:50:05Z",
        "AssetType": "CfdOnIndex",
        "BuySell": "Buy",
        "FilledAmount": 0.01,
        "AveragePrice": 24567.8,
        "LogId": "LOG-1",
        "OrderId": "ORDER-MANUAL-1",
        "PositionId": "POS-1",
        "Status": "FinalFill",
        "SubStatus": "Confirmed",
        "Uic": 4912,
    }
    row.update(changes)
    return row


def test_confirmed_non_pg_final_fill_becomes_manual_marker() -> None:
    marker = parse_manual_fill_v1(
        _activity(),
        expected_account_id="ACC-1",
        products={(4912, "CfdOnIndex"): "US Tech 100 NAS · Saxo 4912"},
        pg_order_ids=frozenset(),
    )
    assert marker is not None
    assert marker.direction == "LONG"
    assert marker.amount == 0.01
    assert marker.execution_price == 24567.8
    assert marker.order_id == "ORDER-MANUAL-1"


def test_pg_order_id_is_never_projected_as_manual() -> None:
    marker = parse_manual_fill_v1(
        _activity(),
        expected_account_id="ACC-1",
        products={(4912, "CfdOnIndex"): "US Tech 100 NAS · Saxo 4912"},
        pg_order_ids=frozenset({"ORDER-MANUAL-1"}),
    )
    assert marker is None


def test_partial_or_rejected_activity_is_not_projected() -> None:
    products = {(4912, "CfdOnIndex"): "US Tech 100 NAS · Saxo 4912"}
    assert parse_manual_fill_v1(
        _activity(Status="Fill"),
        expected_account_id="ACC-1",
        products=products,
        pg_order_ids=frozenset(),
    ) is None
    assert parse_manual_fill_v1(
        _activity(SubStatus="Rejected"),
        expected_account_id="ACC-1",
        products=products,
        pg_order_ids=frozenset(),
    ) is None


def test_fill_from_other_account_is_rejected() -> None:
    marker = parse_manual_fill_v1(
        _activity(AccountId="ACC-OTHER"),
        expected_account_id="ACC-1",
        products={(4912, "CfdOnIndex"): "US Tech 100 NAS · Saxo 4912"},
        pg_order_ids=frozenset(),
    )
    assert marker is None


def test_manual_sell_maps_to_short_and_falls_back_to_price_amount() -> None:
    marker = parse_manual_fill_v1(
        _activity(
            BuySell="Sell",
            FilledAmount=None,
            Amount=0.02,
            AveragePrice=None,
            Price=24555.0,
        ),
        expected_account_id="ACC-1",
        products={(4912, "CfdOnIndex"): "US Tech 100 NAS · Saxo 4912"},
        pg_order_ids=frozenset(),
    )
    assert marker is not None
    assert marker.direction == "SHORT"
    assert marker.amount == 0.02
    assert marker.execution_price == 24555.0


def test_lightweight_payload_uses_distinct_manual_saxo_colors_and_labels() -> None:
    bar = ChartBar(
        market="US Tech 100 NAS · Saxo 4912",
        bar_time="2026-09-20T22:50:00+00:00",
        open=24560.0,
        high=24580.0,
        low=24550.0,
        close=24570.0,
        volume=None,
    )
    buy = AutoTraderTradeMarkerV1(
        executed_at=datetime(2026, 9, 20, 22, 50, 5, tzinfo=timezone.utc),
        execution_price=24567.8,
        direction="LONG",
        amount=0.01,
        strategy_key="manual-saxo",
        net_position_id="POS-1",
        active=False,
        source="SAXO_MANUAL_FILL",
    )
    sell = AutoTraderTradeMarkerV1(
        executed_at=datetime(2026, 9, 20, 22, 50, 20, tzinfo=timezone.utc),
        execution_price=24565.2,
        direction="SHORT",
        amount=0.01,
        strategy_key="manual-saxo",
        net_position_id="POS-2",
        active=False,
        source="SAXO_MANUAL_FILL",
    )
    payload = build_lightweight_live_payload_v1(
        market=bar.market,
        timeframe="1m",
        primary=(bar,),
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=None,
        indicator_names=(),
        indicator_timeframes={},
        chart_height=780,
        price_panel_share=0.5,
        trade_markers=(buy, sell),
    )
    markers = payload["markers"]
    assert markers[0]["color"] == "#16a34a"
    assert markers[0]["text"] == "SAXO BUY"
    assert markers[0]["source"] == "SAXO_MANUAL_FILL"
    assert markers[1]["color"] == "#dc2626"
    assert markers[1]["text"] == "SAXO SELL"


def test_manual_marker_collector_is_read_only_and_low_cadence() -> None:
    source = (ROOT / "manual_saxo_trade_markers_v1.py").read_text(encoding="utf-8").lower()
    assert '"cs/v1/audit/orderactivities"' in source
    assert "default_poll_seconds_v1 = 60" in source
    assert '"finalfill"' in source
    for forbidden in (
        "trade/v2/orders",
        "session.post(",
        "requests.post(",
        "place_order(",
        "_delete(",
    ):
        assert forbidden not in source


def test_one_second_live_marker_update_preserves_manual_source_style() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "live_update.py"
    ).read_text(encoding="utf-8")
    assert '"source": str(marker.source or "")' in source
    assert "source === 'SAXO_MANUAL_FILL'" in source
    assert "SAXO BUY" in source
    assert "SAXO SELL" in source
    assert "'#16a34a' : '#dc2626'" in source


def test_stream_worker_starts_manual_saxo_marker_collector() -> None:
    source = (ROOT / "realtime_worker.py").read_text(encoding="utf-8")
    assert "run_manual_saxo_trade_markers_forever_v1" in source
    assert "PRICEGAUGER_MANUAL_SAXO_MARKER_SECONDS" in source
    assert "pricegauger-manual-saxo-trade-markers" in source
