from __future__ import annotations

from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from build_info import render_build_badge
from realtime_market_data import RealtimeMarketDataStore
from saxo_provider import configured_instruments
from trading_desk import (
    TIMEFRAME_MINUTES,
    last_available_window,
    normalized_close_series,
    resample_bars,
)


st.set_page_config(page_title="TradingDesk · PriceGauger", page_icon="📊", layout="wide")
render_build_badge()

header_left, header_right = st.columns([5, 1])
with header_left:
    st.title("TradingDesk")
    st.caption(
        "Operativ markedsflate basert på PriceGaugers ferdige canonical 1m-bars. "
        "Foundation-versjonen sender ingen ordre og kobler ikke browseren direkte til Saxo."
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
    empty = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.78, 0.22],
    )
    empty.update_xaxes(title_text="UTC", row=2, col=1)
    empty.update_yaxes(title_text="Pris", row=1, col=1)
    empty.update_yaxes(title_text="Volum", row=2, col=1)
    empty.update_layout(
        height=760,
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        annotations=[
            {
                "text": "Grafen fylles automatisk når canonical 1m-bars blir tilgjengelige.",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.55,
                "showarrow": False,
            }
        ],
    )
    st.plotly_chart(empty, use_container_width=True)
    st.stop()

control_market, control_timeframe, control_window, control_mode = st.columns([2.2, 2.4, 2.0, 2.8])
with control_market:
    market = st.selectbox("Hovedmarked", available_markets)
with control_timeframe:
    timeframe = st.radio("Tidsoppløsning", list(TIMEFRAME_MINUTES), horizontal=True, index=1)
with control_window:
    window_hours = st.selectbox("Vindu", [6, 12, 24, 48], index=2, format_func=lambda value: f"{value}t")
with control_mode:
    overlay_mode = st.radio(
        "Overlay-skala",
        ["Normalisert (100)", "Faktisk pris"],
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

now = datetime.now(timezone.utc)
resolved_start = now - timedelta(hours=int(window_hours))
resolved_end = now


def _load(name: str, *, range_start: datetime, range_end: datetime):
    raw = store.load_range(
        market=name,
        start=range_start,
        end=range_end,
        limit=10000,
    )
    return resample_bars(raw, timeframe=timeframe)


try:
    primary = _load(market, range_start=resolved_start, range_end=resolved_end)
except ValueError as exc:
    st.error(f"Ugyldig canonical barserie for {market}: {exc}")
    primary = ()

showing_last_available = False
if not primary:
    latest_primary = latest_by_market.get(market)
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
        f"Ingen bars i siste {window_hours}t fra nå. Viser i stedet siste tilgjengelige "
        f"{window_hours}t frem til {latest_label:%Y-%m-%d %H:%M} UTC."
    )

fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.035,
    row_heights=[0.78, 0.22],
    specs=[[{"secondary_y": True}], [{}]],
)

if primary:
    fig.add_trace(
        go.Candlestick(
            x=[item.bar_time for item in primary],
            open=[item.open for item in primary],
            high=[item.high for item in primary],
            low=[item.low for item in primary],
            close=[item.close for item in primary],
            name=market,
        ),
        row=1,
        col=1,
        secondary_y=False,
    )

    if overlay_mode == "Normalisert (100)":
        normalized_primary = normalized_close_series(primary)
        fig.add_trace(
            go.Scatter(
                x=[stamp for stamp, _ in normalized_primary],
                y=[value for _, value in normalized_primary],
                mode="lines",
                name=f"{market} · 100",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

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

    if overlay_mode == "Normalisert (100)":
        points = normalized_close_series(overlay_bars)
        y_title = "Indeks (100 = første punkt)"
    else:
        points = tuple((item.bar_time, item.close) for item in overlay_bars)
        y_title = "Overlay-pris"

    fig.add_trace(
        go.Scatter(
            x=[stamp for stamp, _ in points],
            y=[value for _, value in points],
            mode="lines",
            name=overlay_market,
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

if overlay_mode == "Normalisert (100)":
    y_title = "Indeks (100 = første punkt)"
else:
    y_title = "Overlay-pris"

volumes = [item.volume for item in primary]
if primary:
    fig.add_trace(
        go.Bar(
            x=[item.bar_time for item in primary],
            y=volumes,
            name="Volum",
            hovertemplate="Volum<br>%{x|%d.%m %H:%M}<br>%{y}<extra></extra>",
        ),
        row=2,
        col=1,
    )
else:
    fig.add_annotation(
        text="Ingen ferdige canonical 1m-bars å vise ennå.",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.55,
        showarrow=False,
    )

fig.update_yaxes(title_text=f"{market} pris", row=1, col=1, secondary_y=False)
fig.update_yaxes(title_text=y_title, row=1, col=1, secondary_y=True)
fig.update_yaxes(title_text="Volum", row=2, col=1)
fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
fig.update_xaxes(title_text="UTC", row=2, col=1)
fig.update_layout(
    height=760,
    margin={"l": 20, "r": 20, "t": 30, "b": 20},
    legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    hovermode="x unified",
)

st.plotly_chart(fig, use_container_width=True)

if not primary:
    st.info(f"Fant ingen ferdige 1m-bars for {market}, heller ikke rundt siste registrerte bar.")
else:
    volume_points = sum(value is not None for value in volumes)
    if volume_points < len(volumes):
        st.caption(
            "Volum vises bare der canonical bar har ekte Saxo chart-volume. "
            "Bars bygget kun fra quote-stream har foreløpig ikke markedsvolum; sample_count brukes aldri som volum."
        )
