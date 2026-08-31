from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED, TEXT_COLOR, build_trading_desk_figure
from trading_desk_indicators import (
    INDICATOR_ATR,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    calculate_indicators,
    clip_indicators,
)


def _bars(count: int, *, start: float = 1.0) -> tuple[ChartBar, ...]:
    origin = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    return tuple(
        ChartBar(
            market="Gold",
            bar_time=origin + timedelta(minutes=index * 5),
            open=start + index - 0.2,
            high=start + index + 0.4,
            low=start + index - 0.5,
            close=start + index,
            volume=100.0 + index,
        )
        for index in range(count)
    )


def test_standard_indicator_periods_and_values() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)

    assert indicators.bollinger_middle[0].bar_time == bars[19].bar_time
    assert indicators.bollinger_middle[-1].value == pytest.approx(60.5)
    assert indicators.macd[0].bar_time == bars[25].bar_time
    assert indicators.macd_signal[0].bar_time == bars[33].bar_time
    assert indicators.rsi[0].bar_time == bars[14].bar_time
    assert indicators.rsi[-1].value == pytest.approx(100.0)

    assert indicators.ema20[0].bar_time == bars[19].bar_time
    assert indicators.ema50[0].bar_time == bars[49].bar_time
    assert indicators.sma50[0].bar_time == bars[49].bar_time
    assert indicators.stochastic_k[0].bar_time == bars[13].bar_time
    assert indicators.stochastic_d[0].bar_time == bars[15].bar_time
    assert 0.0 <= indicators.stochastic_k[-1].value <= 100.0
    assert indicators.atr[0].bar_time == bars[14].bar_time
    assert indicators.atr[-1].value > 0.0


def test_flat_market_rsi_and_stochastic_are_neutral() -> None:
    bars = tuple(
        ChartBar(
            market="Gold",
            bar_time=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
            open=100,
            high=100,
            low=100,
            close=100,
            volume=None,
        )
        for index in range(20)
    )

    indicators = calculate_indicators(bars)
    assert indicators.rsi[-1].value == pytest.approx(50.0)
    assert indicators.stochastic_k[-1].value == pytest.approx(50.0)
    assert indicators.stochastic_d[-1].value == pytest.approx(50.0)
    assert indicators.atr[-1].value == pytest.approx(0.0)


def test_indicator_clipping_keeps_only_visible_chart_range() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)
    clipped = clip_indicators(indicators, start=bars[55].bar_time, end=bars[65].bar_time)

    for points in (
        clipped.bollinger_middle,
        clipped.bollinger_upper,
        clipped.bollinger_lower,
        clipped.macd,
        clipped.macd_signal,
        clipped.macd_histogram,
        clipped.rsi,
        clipped.ema20,
        clipped.ema50,
        clipped.sma50,
        clipped.stochastic_k,
        clipped.stochastic_d,
        clipped.atr,
    ):
        assert all(bars[55].bar_time <= point.bar_time <= bars[65].bar_time for point in points)


def test_chart_renders_default_indicators_compact_and_readable() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI),
    )

    traces = {trace.name: trace for trace in fig.data}
    assert traces["Gold · volum"].yaxis == "y3"
    assert traces["MACD (12,26) · 5 min"].yaxis == "y4"
    assert traces["RSI (14)"].yaxis == "y5"
    assert traces["MACD (12,26) · 5 min"].line.width >= 1.8
    assert traces["RSI (14)"].line.width >= 1.8
    assert fig.layout.height == 780
    assert fig.layout.font.color == TEXT_COLOR
    assert fig.layout.yaxis.tickfont.color == TEXT_COLOR
    assert fig.layout.yaxis.tickfont.size >= 13
    assert fig.layout.yaxis4.tickfont.color == TEXT_COLOR
    assert fig.layout.yaxis5.tickfont.color == TEXT_COLOR


def test_chart_labels_an_independent_macd_timeframe() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_MACD,),
        indicator_timeframes={INDICATOR_MACD: "30m"},
    )

    names = {trace.name for trace in fig.data}
    assert "MACD (12,26) · 30 min" in names
    assert "Signal (9) · 30 min" in names
    assert "MACD histogram · 30 min" in names
    assert fig.layout.yaxis4.title.text == "MACD · 30 min"


def test_chart_renders_optional_price_and_panel_indicators() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(
            INDICATOR_EMA20,
            INDICATOR_EMA50,
            INDICATOR_SMA50,
            INDICATOR_STOCHASTIC,
            INDICATOR_ATR,
        ),
        chart_height=900,
        price_panel_share=0.55,
    )

    traces = {trace.name: trace for trace in fig.data}
    assert traces["EMA 20"].yaxis == "y"
    assert traces["EMA 50"].yaxis == "y"
    assert traces["SMA 50"].yaxis == "y"
    assert traces["Stoch %K (14)"].yaxis == "y4"
    assert traces["Stoch %D (3)"].yaxis == "y4"
    assert traces["ATR (14)"].yaxis == "y5"
    assert list(fig.layout.yaxis4.range) == [0, 100]
    assert fig.layout.height == 900


def test_chart_uses_two_axis_cursor_crosshair() -> None:
    bars = _bars(70)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_MACD, INDICATOR_RSI),
    )

    assert fig.layout.hovermode == "closest"
    assert fig.layout.xaxis.showspikes is True
    assert fig.layout.xaxis.spikesnap == "cursor"
    assert "across" in fig.layout.xaxis.spikemode
    assert fig.layout.yaxis.showspikes is True
    assert fig.layout.yaxis.spikesnap == "cursor"
    assert "across" in fig.layout.yaxis.spikemode
    assert "toaxis" in fig.layout.yaxis.spikemode
    assert fig.layout.yaxis4.showspikes is True
    assert fig.layout.yaxis5.showspikes is True


def test_unknown_indicator_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported TradingDesk indicators"):
        build_trading_desk_figure(
            market="Gold",
            timeframe="5m",
            window_hours=24,
            primary=_bars(2),
            overlays={},
            overlay_mode=OVERLAY_NORMALIZED,
            indicator_names=("CCI",),
        )
