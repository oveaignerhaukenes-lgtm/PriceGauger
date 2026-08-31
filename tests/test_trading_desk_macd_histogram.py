from trading_desk import ChartBar
from trading_desk_chart import (
    MACD_HIST_NEGATIVE_COLOR,
    MACD_HIST_POSITIVE_COLOR,
    OVERLAY_ACTUAL,
    build_trading_desk_figure,
)
from trading_desk_indicators import INDICATOR_MACD, IndicatorPoint, TechnicalIndicators


def _bar(stamp: str, close: float) -> ChartBar:
    return ChartBar(
        market="Brent",
        bar_time=stamp,
        open=close - 0.1,
        high=close + 0.2,
        low=close - 0.2,
        close=close,
        volume=10.0,
    )


def test_macd_histogram_uses_clear_green_and_purple_sign_colors() -> None:
    stamps = ("2026-08-11T00:00:00Z", "2026-08-11T00:05:00Z")
    indicators = TechnicalIndicators(
        macd_histogram=(
            IndicatorPoint(stamps[0], 0.25),
            IndicatorPoint(stamps[1], -0.15),
        ),
    )
    fig = build_trading_desk_figure(
        market="Brent",
        timeframe="5m",
        window_hours=24,
        primary=(_bar(stamps[0], 87.8), _bar(stamps[1], 87.9)),
        overlays={},
        overlay_mode=OVERLAY_ACTUAL,
        indicators=indicators,
        indicator_names=(INDICATOR_MACD,),
    )

    histogram = next(trace for trace in fig.data if trace.name == "MACD histogram · 5 min")
    assert list(histogram.marker.color) == [
        MACD_HIST_POSITIVE_COLOR,
        MACD_HIST_NEGATIVE_COLOR,
    ]
    assert histogram.opacity == 0.92
