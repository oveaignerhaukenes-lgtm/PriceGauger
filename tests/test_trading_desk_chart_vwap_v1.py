from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED, build_trading_desk_figure
from trading_desk_indicators import (
    INDICATOR_ATR,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    INDICATOR_VWAP,
    calculate_indicators,
)


def _bars(count: int = 80) -> tuple[ChartBar, ...]:
    start = datetime(2026, 9, 4, 7, 0, tzinfo=timezone.utc)
    return tuple(
        ChartBar(
            market="US Tech 100 NAS · Saxo 4912",
            bar_time=(start + timedelta(minutes=index)).isoformat(),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=float(index + 1),
        )
        for index in range(count)
    )


def test_vwap_uses_typical_price_weighted_by_real_volume() -> None:
    bars = _bars(2)
    indicators = calculate_indicators(bars)
    assert len(indicators.vwap) == 2
    first_typical = (101.0 + 99.0 + 100.5) / 3.0
    second_typical = (102.0 + 100.0 + 101.5) / 3.0
    assert indicators.vwap[0].value == pytest.approx(first_typical)
    assert indicators.vwap[1].value == pytest.approx((first_typical * 1.0 + second_typical * 2.0) / 3.0)


def test_live_chart_uses_two_line_title_right_scrollable_full_legend() -> None:
    bars = _bars()
    indicators = calculate_indicators(bars)
    selected = (
        INDICATOR_BOLLINGER,
        INDICATOR_MACD,
        INDICATOR_RSI,
        INDICATOR_EMA20,
        INDICATOR_EMA50,
        INDICATOR_SMA50,
        INDICATOR_VWAP,
        INDICATOR_STOCHASTIC,
        INDICATOR_ATR,
    )
    fig = build_trading_desk_figure(
        market="US Tech 100 NAS · Saxo 4912",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=selected,
        indicator_timeframes={INDICATOR_MACD: "1m"},
    )

    assert "<br>" in str(fig.layout.title.text)
    assert fig.layout.legend.orientation == "v"
    assert float(fig.layout.legend.x) > 1.0
    assert float(fig.layout.legend.maxheight) == pytest.approx(0.52)
    assert "hover / scroll" in str(fig.layout.legend.title.text)
    names = [str(item.name) for item in fig.data]
    assert "VWAP · vindu" in names
    assert len(names) > 8
    assert all(item.showlegend is not False for item in fig.data if getattr(item, "name", None))
