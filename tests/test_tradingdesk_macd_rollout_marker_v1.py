from datetime import timedelta

from trading_desk import ChartBar
from tradingdesk_ui.charts.lightweight.direct_contract import (
    MACD_INTRABAR_ROLLOUT_AT_V1,
    MACD_INTRABAR_ROLLOUT_LABEL_V1,
    build_lightweight_direct_live_payload_v1,
)


def _bar(at, close: float) -> ChartBar:
    return ChartBar(
        market="US Tech 100 NAS · Saxo 4912",
        bar_time=at.isoformat(),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=None,
    )


def test_direct_chart_marks_intrabar_macd_rollout_boundary() -> None:
    primary = (
        _bar(MACD_INTRABAR_ROLLOUT_AT_V1 - timedelta(minutes=1), 100.0),
        _bar(MACD_INTRABAR_ROLLOUT_AT_V1 + timedelta(minutes=1), 101.0),
    )
    payload = build_lightweight_direct_live_payload_v1(
        market="US Tech 100 NAS · Saxo 4912",
        timeframe="1m",
        primary=primary,
        overlays={},
        overlay_mode="normalized",
        indicators=None,
        indicator_names=(),
        indicator_timeframes={},
        chart_height=700,
        price_panel_share=0.65,
        rollover_events=(),
    )
    rollout = [item for item in payload["markers"] if item.get("text") == MACD_INTRABAR_ROLLOUT_LABEL_V1]
    assert len(rollout) == 1
    assert rollout[0]["position"] == "aboveBar"
    assert rollout[0]["shape"] == "square"
    assert rollout[0]["time"] == int(primary[1].bar_time.replace("Z", "+00:00") and (MACD_INTRABAR_ROLLOUT_AT_V1 + timedelta(minutes=1)).timestamp())
    assert "macd-rollout:1" in payload["signature"]


def test_rollout_marker_is_absent_outside_visible_history() -> None:
    primary = (
        _bar(MACD_INTRABAR_ROLLOUT_AT_V1 + timedelta(hours=2), 100.0),
        _bar(MACD_INTRABAR_ROLLOUT_AT_V1 + timedelta(hours=2, minutes=1), 101.0),
    )
    payload = build_lightweight_direct_live_payload_v1(
        market="US Tech 100 NAS · Saxo 4912",
        timeframe="1m",
        primary=primary,
        overlays={},
        overlay_mode="normalized",
        indicators=None,
        indicator_names=(),
        indicator_timeframes={},
        chart_height=700,
        price_panel_share=0.65,
        rollover_events=(),
    )
    assert all(item.get("text") != MACD_INTRABAR_ROLLOUT_LABEL_V1 for item in payload["markers"])
    assert "macd-rollout:0" in payload["signature"]
