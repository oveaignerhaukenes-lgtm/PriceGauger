from __future__ import annotations

from trading_desk import ChartBar
from trading_desk_chart import (
    OVERLAY_ACTUAL,
    OVERLAY_NORMALIZED,
    build_trading_desk_figure,
    overlay_axis_title,
)


def _bar(
    minute: str,
    *,
    market: str = "Brent",
    close: float = 80.0,
    volume: float | None = 10.0,
) -> ChartBar:
    return ChartBar(
        market=market,
        bar_time=minute,
        open=close - 0.2,
        high=close + 0.4,
        low=close - 0.5,
        close=close,
        volume=volume,
    )


def test_axis_titles_are_explicit_and_stable() -> None:
    fig = build_trading_desk_figure(
        market="Brent",
        timeframe="5m",
        window_hours=24,
        primary=[_bar("2026-08-07T20:58:00Z", close=80), _bar("2026-08-07T20:59:00Z", close=81)],
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
    )

    assert fig.layout.yaxis.title.text == "Brent · pris"
    assert fig.layout.yaxis.side == "right"
    assert fig.layout.yaxis2.title.text == "Overlay · indeks (100 = start)"
    assert fig.layout.yaxis2.side == "left"
    assert fig.layout.yaxis3.title.text == "Brent · volum"
    assert fig.layout.yaxis3.side == "right"
    assert fig.layout.xaxis2.title.text == "Tid · UTC"
    assert fig.layout.title.text == "Brent · 5m · 24t"


def test_normalized_overlay_uses_secondary_axis_and_volume_uses_lower_panel() -> None:
    primary = [
        _bar("2026-08-07T20:58:00Z", close=80, volume=100),
        _bar("2026-08-07T20:59:00Z", close=82, volume=120),
    ]
    gold = [
        _bar("2026-08-07T20:58:00Z", market="Gold", close=4000),
        _bar("2026-08-07T20:59:00Z", market="Gold", close=4040),
    ]

    fig = build_trading_desk_figure(
        market="Brent",
        timeframe="5m",
        window_hours=24,
        primary=primary,
        overlays={"Gold": gold},
        overlay_mode=OVERLAY_NORMALIZED,
    )

    traces = {trace.name: trace for trace in fig.data}
    assert traces["Brent · candles"].yaxis == "y"
    assert traces["Brent · indeks"].yaxis == "y2"
    assert traces["Gold"].yaxis == "y2"
    assert traces["Brent · volum"].yaxis == "y3"
    assert list(traces["Gold"].y) == [100.0, 101.0]


def test_last_close_reference_is_present_on_price_panel() -> None:
    fig = build_trading_desk_figure(
        market="Brent",
        timeframe="1m",
        window_hours=6,
        primary=[_bar("2026-08-07T20:59:00Z", close=81.25)],
        overlays={},
        overlay_mode=OVERLAY_ACTUAL,
    )

    assert any(shape.y0 == 81.25 and shape.y1 == 81.25 for shape in fig.layout.shapes)
    assert any("Siste 81.25" in str(annotation.text) for annotation in fig.layout.annotations)
    assert fig.layout.yaxis2.title.text == "Overlay · faktisk pris"


def test_empty_chart_keeps_operational_axes_visible() -> None:
    fig = build_trading_desk_figure(
        market="Brent",
        timeframe="5m",
        window_hours=24,
        primary=(),
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        empty_message="Ingen data ennå",
    )

    assert len(fig.data) == 0
    assert fig.layout.yaxis.title.text == "Brent · pris"
    assert fig.layout.yaxis3.title.text == "Brent · volum"
    assert any(annotation.text == "Ingen data ennå" for annotation in fig.layout.annotations)


def test_overlay_axis_title_rejects_unknown_mode() -> None:
    assert overlay_axis_title(OVERLAY_NORMALIZED) == "Overlay · indeks (100 = start)"
    assert overlay_axis_title(OVERLAY_ACTUAL) == "Overlay · faktisk pris"
