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
from trading_desk_indicators import (
    DEFAULT_INDICATORS,
    INDICATOR_OPTIONS,
    INDICATOR_WARMUP_PERIODS,
    calculate_indicators,
    clip_indicators,
)
from trading_desk_product_panel import render_saxo_product_panel


LIVE_CHART_REFRESH_SECONDS = 5
QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m", "1h")
TIMEFRAME_STATE_KEY = "tradingdesk_timeframe"


st.set_page_config(page_title="TradingDesk · PriceGauger", page_icon="📊", layout="wide")
render_build_badge()

# Keep Plotly's graph operators accessible without covering the chart title/legend.
st.markdown(
    """
    <style>
    div[data-testid="stPlotlyChart"] .modebar {
        top: 3.2rem !important;
        right: .35rem !important;
        flex-direction: column !important;
        background: rgba(255,255,255,.94) !important;
        border: 1px solid rgba(17,24,39,.16) !important;
        border-radius: .45rem !important;
        padding: .18rem !important;
    }
    div[data-testid="stPlotlyChart"] .modebar-group {
        display: flex !important;
        flex-direction: column !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

header_left, header_right = st.columns([5, 1])
with header_left:
    st.title("TradingDesk")
    st.caption(
        "Operativ markedsflate for canonical OHLCV. Venstre side er global navigasjon; "
        "graf-, indikator- og AutoTrader-kontroller ligger samlet til høyre på bred skjerm."
    )
with header_right:
    st.page_link("pages/0_Oversikt.py", label="Til Oversikt", icon="📡")

store = RealtimeMarketDataStore()
configured = configured_instruments()
configured_markets = list(configured)
latest_by_market = {market: store.load_latest_bar(market=market) for market in configured_markets}
available_markets = [market for market in configured_markets if latest_by_market[market] is not None]
unavailable_markets = [market for market in configured_markets if market not in available_markets]

chart_column, controls_column = st.columns([4.8, 1.45], gap="large")

if not available_markets:
    with controls_column:
        st.subheader("Kontroller")
        st.info("Grafinnstillinger blir tilgjengelige når canonical markedsbarer finnes.")
    with chart_column:
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
        st.plotly_chart(empty, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
    st.stop()

if st.session_state.get(TIMEFRAME_STATE_KEY) not in TIMEFRAME_MINUTES:
    st.session_state[TIMEFRAME_STATE_KEY] = "5m"


def _select_timeframe(value: str) -> None:
    st.session_state[TIMEFRAME_STATE_KEY] = value


with controls_column:
    st.subheader("Kontroller")

    with st.expander("Graf", expanded=True):
        market = st.selectbox("Marked", available_markets)

        st.markdown("**Timeframe**")
        timeframe_rows = (QUICK_TIMEFRAMES[:3], QUICK_TIMEFRAMES[3:])
        for row_index, values in enumerate(timeframe_rows):
            quick_columns = st.columns(len(values), gap="small")
            for column, value in zip(quick_columns, values):
                with column:
                    label = "1t" if value == "1h" else value
                    st.button(
                        label,
                        key=f"tradingdesk_tf_{row_index}_{value}",
                        help=f"Bytt direkte til {value}",
                        type="primary" if st.session_state[TIMEFRAME_STATE_KEY] == value else "secondary",
                        use_container_width=True,
                        on_click=_select_timeframe,
                        args=(value,),
                    )
        timeframe = st.session_state[TIMEFRAME_STATE_KEY]

        window_hours = st.selectbox("Vindu", [6, 12, 24, 48], index=2, format_func=lambda value: f"{value}t")
        overlay_mode = st.radio("Overlay-akse", [OVERLAY_NORMALIZED, OVERLAY_ACTUAL], index=0)

        overlay_options = [item for item in available_markets if item != market]
        overlays = st.multiselect("Sammenlign med", overlay_options)

    with st.expander("Indikatorer", expanded=True):
        indicator_names = st.multiselect(
            "Vis indikatorer",
            list(INDICATOR_OPTIONS),
            default=list(DEFAULT_INDICATORS),
            help=(
                "Bollinger/EMA/SMA ligger på prisgrafen. MACD, RSI, Stochastic og ATR får egne paneler. "
                "De tre opprinnelige indikatorene er valgt som standard."
            ),
        )

        chart_height = st.slider(
            "Total grafhøyde",
            min_value=620,
            max_value=1100,
            value=780,
            step=20,
            help="Squash eller strekk hele chart-stacken uten å endre data eller indikatorberegning.",
        )
        price_panel_pct = st.slider(
            "Hovedgrafens andel",
            min_value=40,
            max_value=65,
            value=50,
            step=5,
            help="Fordeler mer eller mindre av høyden til candlestick-panelet. Resten deles mellom underpanelene.",
        )

    with st.expander(f"Handel · {market}", expanded=False):
        st.caption(
            "Hurtighandel bruker samme Mini/KO-, sizing-, pre-check- og SIM-execution-motor som AutoTrader-siden. "
            "Markedet følger grafen; TradingDesk har ingen separat ordrelogikk."
        )
        render_saxo_product_panel(market)
        st.page_link("pages/6_AutoTrader_POC.py", label="Åpne full AutoTrader", icon="🧪")

    if unavailable_markets:
        st.caption("Uten canonical bars: " + ", ".join(unavailable_markets))

    with st.expander("Status", expanded=False):
        st.caption(
            f"Canonical bars leses på nytt hvert {LIVE_CHART_REFRESH_SECONDS}. sekund. "
            "Ferdige candles og indikatorer oppdateres når neste 1m-bar er lagret."
        )


def _load(name: str, *, range_start: datetime, range_end: datetime, limit: int = 10000):
    raw = store.load_range(market=name, start=range_start, end=range_end, limit=limit)
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
            resolved_start, resolved_end = last_available_window(latest_primary.bar_time, window_hours=int(window_hours))
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
            overlay_bars = _load(overlay_market, range_start=resolved_start, range_end=resolved_end)
        except ValueError as exc:
            st.warning(f"Hopper over {overlay_market}: {exc}")
            continue
        if not overlay_bars:
            st.warning(f"Ingen bars for {overlay_market} i vist tidsvindu.")
            continue
        loaded_overlays[overlay_market] = overlay_bars

    technical = None
    if primary and indicator_names:
        warmup_minutes = TIMEFRAME_MINUTES[timeframe] * INDICATOR_WARMUP_PERIODS
        warmup_start = resolved_start - timedelta(minutes=warmup_minutes)
        try:
            indicator_source = _load(market, range_start=warmup_start, range_end=resolved_end, limit=20000)
            technical = calculate_indicators(indicator_source)
            technical = clip_indicators(technical, start=primary[0].bar_time, end=primary[-1].bar_time)
        except ValueError as exc:
            st.warning(f"Kunne ikke beregne tekniske indikatorer for {market}: {exc}")

    latest_display = "ingen data"
    if primary:
        latest_display = f"{primary[-1].close:g} @ {utc(primary[-1].bar_time):%Y-%m-%d %H:%M} UTC"

    st.caption(f"**{market}** · {timeframe} · {window_hours}t · siste close {latest_display}")

    fig = build_trading_desk_figure(
        market=market,
        timeframe=timeframe,
        window_hours=int(window_hours),
        primary=primary,
        overlays=loaded_overlays,
        overlay_mode=overlay_mode,
        indicators=technical,
        indicator_names=indicator_names,
        chart_height=chart_height,
        price_panel_share=price_panel_pct / 100.0,
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


with chart_column:
    _fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
    if _fragment is not None:
        _fragment(run_every=f"{LIVE_CHART_REFRESH_SECONDS}s")(_render_live_chart)()
    else:
        _render_live_chart()
