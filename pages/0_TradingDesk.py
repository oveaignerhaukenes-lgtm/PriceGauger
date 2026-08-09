from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from build_info import render_build_badge
from realtime_market_data import RealtimeMarketDataStore
from saxo_provider import configured_instruments
from trading_desk import TIMEFRAME_MINUTES, last_available_window, resample_bars, utc
from trading_desk_chart import (
    OVERLAY_ACTUAL,
    OVERLAY_NORMALIZED,
    build_trading_desk_figure,
)
from trading_desk_clock import candle_countdown
from trading_desk_product_panel import render_saxo_product_panel


LIVE_CHART_REFRESH_SECONDS = 5


st.set_page_config(page_title="TradingDesk · PriceGauger", page_icon="📊", layout="wide")
render_build_badge()

header_left, header_right = st.columns([5, 1])
with header_left:
    st.title("TradingDesk")
    st.caption(
        "Operativ markedsflate for canonical OHLCV. Pris, overlays og volum har faste, "
        "tydelig merkede akser; ingen ordre sendes fra foundation-visningen."
    )
with header_right:
    st.page_link("pages/0_Oversikt.py", label="Til Oversikt", icon="📡")

store = RealtimeMarketDataStore()
configured = configured_instruments()
configured_markets = list(configured)
latest_by_market = {
    market: store.load_latest_bar(market=market) for market in configured_markets
}
available_markets = [
    market for market in configured_markets if latest_by_market[market] is not None
]
unavailable_markets = [market for market in configured_markets if market not in available_markets]

if not available_markets:
    st.info("Ingen canonical 1m-markedsbarer er tilgjengelige for TradingDesk ennå.")
    if unavailable_markets:
        st.caption("Konfigurert uten tilgjengelige bars: " + ", ".join(unavailable_markets))
    empty = build_trading_desk_figure(
        market="Marked",
        timeframe="5m",
        window_hours=24,
        primary=(),
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        empty_message="Grafen fylles automatisk når canonical 1m-bars blir tilgjengelige.",
    )
    st.plotly_chart(
        empty,
        use_container_width=True,
        config={"scrollZoom": True, "displaylogo": False},
    )
    st.stop()

control_market, control_timeframe, control_window, control_mode = st.columns([2.2, 2.8, 1.6, 2.8])
with control_market:
    market = st.selectbox("Marked", available_markets)
with control_timeframe:
    timeframe = st.radio("Timeframe", list(TIMEFRAME_MINUTES), horizontal=True, index=1)
with control_window:
    window_hours = st.selectbox(
        "Vindu",
        [6, 12, 24, 48],
        index=2,
        format_func=lambda value: f"{value}t",
    )
with control_mode:
    overlay_mode = st.radio(
        "Overlay-akse",
        [OVERLAY_NORMALIZED, OVERLAY_ACTUAL],
        horizontal=True,
        index=0,
    )

overlay_options = [item for item in available_markets if item != market]
overlays = st.multiselect("Sammenlign med", overlay_options)

if unavailable_markets:
    st.caption(
        "Konfigurerte markeder uten tilgjengelige canonical bars vises ikke i velgeren: "
        + ", ".join(unavailable_markets)
    )

st.caption(
    f"Chartet leser canonical bars på nytt hvert {LIVE_CHART_REFRESH_SECONDS}. sekund. "
    "Ferdige candles oppdateres når neste 1m-bar er lagret; ingen Telegram- eller forecastkriterier brukes."
)


_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))


def _render_candle_clock() -> None:
    countdown = candle_countdown(datetime.now(timezone.utc), timeframe=timeframe)
    clock_col, boundary_col, note_col = st.columns([1.2, 1.5, 5])
    clock_col.metric("Neste candlegrense", countdown.label)
    boundary_col.metric("UTC", countdown.next_boundary.strftime("%H:%M:%S"))
    note_col.caption(
        "Nedtellingen følger canonical UTC-grenser. Ny ferdig candle vises først når markedet "
        "har levert data og PriceGauger har lagret den."
    )


if _fragment is not None:
    _fragment(run_every="1s")(_render_candle_clock)()
else:
    _render_candle_clock()


def _load(name: str, *, range_start: datetime, range_end: datetime):
    raw = store.load_range(
        market=name,
        start=range_start,
        end=range_end,
        limit=10000,
    )
    return resample_bars(raw, timeframe=timeframe)


def _render_live_chart() -> None:
    now = datetime.now(timezone.utc)
    resolved_start = now - timedelta(hours=int(window_hours))
    resolved_end = now

    try:
        primary = _load(market, range_start=resolved_start, range_end=resolved_end)
    except ValueError as exc:
        st.error(f"Ugyldig canonical barserie for {market}: {exc}")
        primary = ()

    showing_last_available = False
    if not primary:
        latest_primary = store.load_latest_bar(market=market)
        if latest_primary is not None:
            resolved_start, resolved_end = last_available_window(
                latest_primary.bar_time,
                window_hours=int(window_hours),
            )
            try:
                primary = _load(market, range_start=resolved_start, range_end=resolved_end)
                showing_last_available = bool(primary)
            except ValueError as exc:
                st.error(f"Ugyldig canonical barserie for {market}: {exc}")
                primary = ()

    if showing_last_available:
        latest_label = resolved_end - timedelta(minutes=1)
        st.caption(
            f"Markedet har ingen bars i siste {window_hours}t fra nå. Viser siste tilgjengelige "
            f"{window_hours}t frem til {latest_label:%Y-%m-%d %H:%M} UTC."
        )

    loaded_overlays: dict[str, tuple] = {}
    for overlay_market in overlays:
        try:
            overlay_bars = _load(
                overlay_market,
                range_start=resolved_start,
                range_end=resolved_end,
            )
        except ValueError as exc:
            st.warning(f"Hopper over {overlay_market}: {exc}")
            continue
        if not overlay_bars:
            st.warning(f"Ingen bars for {overlay_market} i vist tidsvindu.")
            continue
        loaded_overlays[overlay_market] = overlay_bars

    latest_display = "ingen data"
    if primary:
        latest_display = f"{primary[-1].close:g} @ {utc(primary[-1].bar_time):%Y-%m-%d %H:%M} UTC"

    st.caption(
        f"**{market}** · {timeframe} · {window_hours}t · siste close {latest_display}  |  "
        f"**høyre akse:** {market} pris  ·  **venstre akse:** overlay  ·  **nedre panel:** volum"
    )

    fig = build_trading_desk_figure(
        market=market,
        timeframe=timeframe,
        window_hours=int(window_hours),
        primary=primary,
        overlays=loaded_overlays,
        overlay_mode=overlay_mode,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )

    if not primary:
        st.info(f"Fant ingen ferdige 1m-bars for {market}, heller ikke rundt siste registrerte bar.")
    else:
        volume_points = sum(item.volume is not None for item in primary)
        if volume_points < len(primary):
            st.caption(
                "Volum vises bare der canonical bar har ekte Saxo chart-volume. "
                "Bars bygget kun fra quote-stream har foreløpig ikke markedsvolum; sample_count brukes aldri som volum."
            )


if _fragment is not None:
    _fragment(run_every=f"{LIVE_CHART_REFRESH_SECONDS}s")(_render_live_chart)()
else:
    _render_live_chart()

render_saxo_product_panel(market)
