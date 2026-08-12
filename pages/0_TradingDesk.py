from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from autotrader_macd_mode import (
    AUTOTRADER_MODE_MACD_30M,
    AUTOTRADER_MODE_MANUAL,
    AUTOTRADER_MODES,
    latest_macd_crossover_intent,
)
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
QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m")
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
        "Operativ markedsflate for canonical OHLCV. Pris, overlays, volum og tekniske indikatorer "
        "bruker samme ferdige candles; Saxo-produktpanelet holdes separat fra chart-refresh."
    )
with header_right:
    st.page_link("pages/0_Oversikt.py", label="Til Oversikt", icon="📡")

store = RealtimeMarketDataStore()
configured = configured_instruments()
configured_markets = list(configured)
latest_by_market = {market: store.load_latest_bar(market=market) for market in configured_markets}
available_markets = [market for market in configured_markets if latest_by_market[market] is not None]
unavailable_markets = [market for market in configured_markets if market not in available_markets]

if not available_markets:
    with st.sidebar:
        st.header("Graf")
        st.info("Grafinnstillinger blir tilgjengelige når canonical markedsbarer finnes.")
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


with st.sidebar:
    st.header("Graf")
    market = st.selectbox("Marked", available_markets)

    st.markdown("**Timeframe**")
    quick_columns = st.columns(len(QUICK_TIMEFRAMES), gap="small")
    for column, value in zip(quick_columns, QUICK_TIMEFRAMES):
        with column:
            st.button(
                value.removesuffix("m"),
                key=f"tradingdesk_tf_{value}",
                help=f"Bytt direkte til {value}",
                type="primary" if st.session_state[TIMEFRAME_STATE_KEY] == value else "secondary",
                use_container_width=True,
                on_click=_select_timeframe,
                args=(value,),
            )
    st.caption("minutter")
    st.button(
        "1 time",
        key="tradingdesk_tf_1h",
        type="primary" if st.session_state[TIMEFRAME_STATE_KEY] == "1h" else "secondary",
        use_container_width=True,
        on_click=_select_timeframe,
        args=("1h",),
    )
    timeframe = st.session_state[TIMEFRAME_STATE_KEY]

    window_hours = st.selectbox("Vindu", [6, 12, 24, 48], index=2, format_func=lambda value: f"{value}t")
    overlay_mode = st.radio("Overlay-akse", [OVERLAY_NORMALIZED, OVERLAY_ACTUAL], index=0)

    overlay_options = [item for item in available_markets if item != market]
    overlays = st.multiselect("Sammenlign med", overlay_options)
    indicator_names = st.multiselect(
        "Indikatorer",
        list(INDICATOR_OPTIONS),
        default=list(DEFAULT_INDICATORS),
        help=(
            "Bollinger/EMA/SMA ligger på prisgrafen. MACD, RSI, Stochastic og ATR får egne paneler. "
            "De tre opprinnelige indikatorene er valgt som standard."
        ),
    )

    with st.expander("Panelstørrelse", expanded=False):
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

    st.divider()
    st.header("AutoTrader")
    autotrader_mode = st.selectbox(
        "Modus",
        AUTOTRADER_MODES,
        index=0,
        help="Prøvemodusen observerer 30m MACD-kryss og lager et position-intent. Den sender ikke ordre ennå.",
    )
    autotrader_amount = st.number_input(
        "Steg per kryss",
        min_value=0.000001,
        value=1.0,
        step=1.0,
        format="%.6f",
        disabled=autotrader_mode == AUTOTRADER_MODE_MANUAL,
        help="Mengden som senere skal legges til ved oppkryss eller selges/reduseres ved nedkryss.",
    )

    if unavailable_markets:
        st.caption("Uten tilgjengelige canonical bars: " + ", ".join(unavailable_markets))

    with st.expander("Om grafen"):
        st.caption(
            f"Canonical bars leses på nytt hvert {LIVE_CHART_REFRESH_SECONDS}. sekund. "
            "Ferdige candles og indikatorer oppdateres når neste 1m-bar er lagret."
        )


def _load(name: str, *, range_start: datetime, range_end: datetime, limit: int = 10000, selected_timeframe: str | None = None):
    raw = store.load_range(market=name, start=range_start, end=range_end, limit=limit)
    return resample_bars(raw, timeframe=selected_timeframe or timeframe)


def _render_autotrader_status() -> None:
    with st.sidebar:
        if autotrader_mode != AUTOTRADER_MODE_MACD_30M:
            st.caption("Manuell modus: ingen automatiske signalintents aktive.")
            return

        now = datetime.now(timezone.utc)
        source_start = now - timedelta(days=14)
        try:
            bars_30m = _load(
                market,
                range_start=source_start,
                range_end=now,
                limit=30000,
                selected_timeframe="30m",
            )
            intent = latest_macd_crossover_intent(
                bars_30m,
                market=market,
                amount=float(autotrader_amount),
            )
        except ValueError as exc:
            st.warning(f"MACD 30m kunne ikke evalueres: {exc}")
            return

        st.caption("SIM/dry-run · kun lukkede 30m-candles · ingen ordre sendes")
        if intent is None:
            st.info("Ingen nytt 30m MACD-kryss på siste ferdige candle.")
            return

        action = "ØK LONG / KJØP" if intent.side == "Buy" else "REDUSER / SELG"
        st.success(f"{action} {intent.amount:g} · {market}")
        st.caption(
            f"Kryss @ {intent.bar_time} · MACD {intent.macd:.6g} · signal {intent.signal:.6g}"
        )
        st.caption(f"Event key: {intent.event_key}")


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


_render_autotrader_status()

_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
if _fragment is not None:
    _fragment(run_every=f"{LIVE_CHART_REFRESH_SECONDS}s")(_render_live_chart)()
else:
    _render_live_chart()

render_saxo_product_panel(market)
