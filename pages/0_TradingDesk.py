from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import streamlit as st

from build_info import render_build_badge
from companion_ui_v2 import render_companion_panel_v2
from realtime_market_data import RealtimeMarketDataStore
from saxo_chart_live import (
    FormingCandleStore,
    forming_candle_event_age_seconds,
    live_chart_refresh_seconds,
    merge_forming_candle_for_display,
)
from time_display_v2 import localize_plotly_figure_v2, oslo_label
from trading_desk import TIMEFRAME_MINUTES, last_available_window, resample_bars
from trading_desk_chart import (
    OVERLAY_ACTUAL,
    OVERLAY_NORMALIZED,
    build_trading_desk_figure,
)
from trading_desk_indicators import (
    DEFAULT_INDICATORS,
    INDICATOR_MACD,
    INDICATOR_OPTIONS,
    INDICATOR_SWING_BANDS,
    INDICATOR_WARMUP_PERIODS,
    calculate_indicators,
    clip_indicators,
)
from trading_desk_swing_bands import add_swing_bands_to_figure
from trading_desk_v2_context import TradingDeskV2Context, load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import (
    render_tradingdesk_automanage_panel_v2,
    render_tradingdesk_automanage_pnl_chart_v2,
)
from v2_forecast_visualization import (
    V2_FORECAST_CSS,
    render_v2_forecast_chart,
    render_v2_technical_explanation,
)


V2_ANALYSIS_REFRESH_SECONDS = 60
QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m", "1h")
TIMEFRAME_STATE_KEY = "tradingdesk_timeframe"
MACD_TIMEFRAME_STATE_KEY = "tradingdesk_macd_timeframe"
AUTO_REFRESH_STATE_KEY = "tradingdesk_auto_refresh"
MARKET_STATE_KEY = "tradingdesk-v2-market"


st.set_page_config(page_title="TradingDesk · PriceGauger", page_icon="📊", layout="wide")
render_build_badge()
st.markdown(V2_FORECAST_CSS, unsafe_allow_html=True)

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
        "V2 cockpit: valgt marked og instrument kommer fra den dynamiske v2-registryen; "
        "forecast, runtime health og TA Analyst følger samme persisterte v2-workspace."
    )
with header_right:
    st.page_link("pages/0_Oversikt.py", label="Til Oversikt", icon="📡")

store = RealtimeMarketDataStore()
forming_store = FormingCandleStore()
try:
    baseline_contexts = load_trading_desk_contexts_v2()
except Exception as exc:
    st.warning(f"TradingDesk kunne ikke lese v2-workspaces: {exc}")
    st.caption("Legacy analyse/forecast brukes ikke som skjult fallback etter v2-cutover.")
    st.stop()

available_markets = sorted(baseline_contexts)
if not available_markets:
    st.info("Venter på aktive persisterte v2 workspaces før TradingDesk kan åpnes.")
    st.caption("Legacy analyse/forecast brukes ikke som skjult fallback etter v2-cutover.")
    st.stop()

requested_market = str(st.query_params.get("market", "") or "").strip()
if st.session_state.get(MARKET_STATE_KEY) not in available_markets:
    st.session_state[MARKET_STATE_KEY] = (
        requested_market if requested_market in available_markets else available_markets[0]
    )
if st.session_state.get(TIMEFRAME_STATE_KEY) not in TIMEFRAME_MINUTES:
    st.session_state[TIMEFRAME_STATE_KEY] = "5m"
if st.session_state.get(MACD_TIMEFRAME_STATE_KEY) not in TIMEFRAME_MINUTES:
    st.session_state[MACD_TIMEFRAME_STATE_KEY] = "30m"
if AUTO_REFRESH_STATE_KEY not in st.session_state:
    st.session_state[AUTO_REFRESH_STATE_KEY] = True


def _select_timeframe(value: str) -> None:
    st.session_state[TIMEFRAME_STATE_KEY] = value


def _persist_market_selection() -> None:
    selected = str(st.session_state.get(MARKET_STATE_KEY, "") or "")
    if selected in available_markets:
        st.query_params["market"] = selected


def _timeframe_label(value: str) -> str:
    return f"{TIMEFRAME_MINUTES[value]} min"


def _horizon_label(seconds: int) -> str:
    value = int(seconds)
    if value < 3600:
        return f"{value // 60:g}m"
    hours = value / 3600.0
    if abs(hours - 168.0) <= 1e-6:
        return "7d"
    return f"{hours:g}t"


chart_column, controls_column = st.columns([4.8, 1.45], gap="large")

with controls_column:
    st.subheader("Kontroller")

    with st.expander("V2 marked / analyse", expanded=True):
        market = st.selectbox(
            "Marked",
            available_markets,
            key=MARKET_STATE_KEY,
            on_change=_persist_market_selection,
        )
        if str(st.query_params.get("market", "") or "") != market:
            st.query_params["market"] = market
        baseline_context = baseline_contexts[market]
        baseline_view = baseline_context.forecast

        horizons = tuple(sorted(int(value) for value in baseline_view.available_horizons))
        default_horizon = min(horizons, key=lambda value: (abs(value - 4 * 3600), value))
        selected_horizon = st.selectbox(
            "Prognosehorisont",
            horizons,
            index=horizons.index(default_horizon),
            format_func=_horizon_label,
            key=f"tradingdesk-v2-horizon:{market}",
        )
        use_interpreter = st.checkbox(
            "Technical Interpreter",
            value=False,
            disabled=not baseline_view.interpreter_available,
            help=(
                "Komponerer bare fingerprint-matchet cached v2 layer-output."
                if baseline_view.interpreter_available
                else "Ingen kompatibel cached Technical Interpreter-output finnes for dette workspace-snapshotet."
            ),
            key=f"tradingdesk-v2-interpreter:{market}",
        )

        st.caption(f"market_id {baseline_context.market_id}")
        if baseline_context.instrument is None:
            st.warning("Ingen aktiv/subscribed v2-instrumentkilde. Chart og AutoManager er deaktivert for markedet.")
        else:
            st.caption(
                f"instrument_id {baseline_context.instrument.instrument_id} · {baseline_context.instrument_label}"
            )

    with st.expander("Graf", expanded=True):
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

        overlay_options = [
            item
            for item in available_markets
            if item != market and baseline_contexts[item].instrument is not None
        ]
        overlays = st.multiselect("Sammenlign med", overlay_options)

    with st.expander("Indikatorer", expanded=True):
        indicator_names = st.multiselect(
            "Vis indikatorer",
            list(INDICATOR_OPTIONS),
            default=list(DEFAULT_INDICATORS),
            help=(
                "Bollinger/EMA/SMA og Swing high/low ligger på prisgrafen. MACD, RSI, Stochastic og ATR får egne paneler. "
                "Swing-sonene er bekreftede lokale pivoter og er kun en teknisk visualisering."
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

    with st.expander("Status", expanded=False):
        auto_refresh = st.toggle(
            "Autooppdater TradingDesk",
            key=AUTO_REFRESH_STATE_KEY,
            help=(
                "På som standard. Analyse og chart oppdateres i separate fragmenter, slik at resten av siden "
                "ikke skal fade eller lastes på nytt."
            ),
        )
        if auto_refresh:
            st.caption(
                "Live-candlen oppdateres hvert sekund når Saxo chart-streamen er aktiv, ellers hvert femte sekund. "
                f"V2 workspace/health/TA Analyst oppdateres hvert {V2_ANALYSIS_REFRESH_SECONDS}. sekund."
            )
        else:
            st.caption("Autooppdatering er pauset. Siden oppdateres ved brukerhandling eller nettleser-refresh.")
        st.caption(
            "Chartet og v2-runtime konsumerer canonical 1m-data. Kjent Saxo-forsinkelse vises eksplisitt og regnes ikke som feed-feil når strømmen ellers er konsistent."
        )


def _load_for_timeframe(
    name: str,
    *,
    selected_timeframe: str,
    range_start: datetime,
    range_end: datetime,
    limit: int = 10000,
):
    raw = store.load_range(market=name, start=range_start, end=range_end, limit=limit)
    return resample_bars(raw, timeframe=selected_timeframe)


def _load(name: str, *, range_start: datetime, range_end: datetime, limit: int = 10000):
    return _load_for_timeframe(
        name,
        selected_timeframe=timeframe,
        range_start=range_start,
        range_end=range_end,
        limit=limit,
    )


def _load_active_context() -> TradingDeskV2Context | None:
    try:
        contexts = load_trading_desk_contexts_v2(
            requested_horizons={market: int(selected_horizon)},
            interpreter_by_market={market: bool(use_interpreter)},
        )
    except Exception as exc:
        st.warning(f"Kunne ikke oppdatere v2 TradingDesk-context: {exc}")
        return None
    return contexts.get(market)


def _render_v2_analysis() -> None:
    context = _load_active_context()
    if context is None:
        st.info("V2-workspace er ikke tilgjengelig for valgt marked/horizon.")
        return

    view = context.forecast
    status_label = f"{context.health.status} · {context.health.detail}"
    st.subheader("PriceGauger v2")
    identity = f"market_id {context.market_id}"
    if context.instrument is not None:
        identity += f" · instrument_id {context.instrument.instrument_id} · {context.instrument.provider}:{context.instrument.provider_instrument_id}"
    st.caption(f"{identity} · {view.recipe_label} · snapshot {oslo_label(view.as_of)} · {status_label}")

    chart = render_v2_forecast_chart(view)
    explanation = render_v2_technical_explanation(view)
    st.markdown(
        f'<div class="pg-v2-layout">{chart}{explanation}</div>',
        unsafe_allow_html=True,
    )

    metrics = st.columns(4)
    metrics[0].metric("Retning", view.direction)
    metrics[1].metric("Forventet move", f"{view.expected_return * 100:+.3f}%")
    metrics[2].metric("TA confidence", f"{view.confidence:.0%}")
    metrics[3].metric("Horisont", _horizon_label(view.horizon_seconds))

    if context.health.status != "HEALTHY":
        st.warning(f"V2 analysis health: {context.health.status} · {context.health.detail}")

    render_companion_panel_v2(view)


def _render_live_chart() -> None:
    context = _load_active_context()
    if context is None or context.instrument is None:
        st.info("Live chart venter på eksplisitt aktiv v2-instrumentidentitet.")
        return

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
            f"{window_hours}t frem til {oslo_label(latest_label)}."
        )

    loaded_overlays: dict[str, tuple] = {}
    for overlay_market in overlays:
        overlay_context = baseline_contexts.get(overlay_market)
        if overlay_context is None or overlay_context.instrument is None:
            st.warning(f"Hopper over {overlay_market}: mangler aktiv v2-instrumentidentitet.")
            continue
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
            macd_timeframe = st.session_state[MACD_TIMEFRAME_STATE_KEY]
            if INDICATOR_MACD in indicator_names and macd_timeframe != timeframe:
                macd_warmup_minutes = TIMEFRAME_MINUTES[macd_timeframe] * INDICATOR_WARMUP_PERIODS
                macd_source = _load_for_timeframe(
                    market,
                    selected_timeframe=macd_timeframe,
                    range_start=resolved_start - timedelta(minutes=macd_warmup_minutes),
                    range_end=resolved_end,
                    limit=20000,
                )
                macd = clip_indicators(
                    calculate_indicators(macd_source),
                    start=primary[0].bar_time,
                    end=primary[-1].bar_time,
                )
                technical = replace(
                    technical,
                    macd=macd.macd,
                    macd_signal=macd.macd_signal,
                    macd_histogram=macd.macd_histogram,
                )
        except ValueError as exc:
            st.warning(f"Kunne ikke beregne tekniske indikatorer for {market}: {exc}")

    forming = None
    try:
        candidate = forming_store.load(market=market)
        if (
            candidate is not None
            and str(candidate.uic) == str(context.instrument.provider_instrument_id)
            and candidate.asset_type == context.instrument.asset_type
            and (forming_candle_event_age_seconds(candidate) or 0.0) <= 8.0
        ):
            forming = candidate
    except Exception:
        forming = None
    display_primary = merge_forming_candle_for_display(primary, forming=forming, timeframe=timeframe)

    latest_display = "ingen data"
    if display_primary:
        latest_display = f"{display_primary[-1].close:g} @ {oslo_label(display_primary[-1].bar_time)}"

    chart_header, macd_control = st.columns([4.2, 1.2])
    with chart_header:
        st.subheader("Live chart")
    with macd_control:
        macd_timeframe = st.session_state[MACD_TIMEFRAME_STATE_KEY]
        with st.popover(f"MACD · {_timeframe_label(macd_timeframe)}", use_container_width=True):
            st.radio(
                "MACD-timeframe",
                QUICK_TIMEFRAMES,
                key=MACD_TIMEFRAME_STATE_KEY,
                format_func=_timeframe_label,
                help="Velger timeframe for MACD-panelet i chartet.",
            )
            st.caption("Kun chartvisning. Den armerte AutoManager-piloten beholder sin eksplisitte 30 min-strategi.")
    st.caption(
        f"**{market}** · v2 instrument_id {context.instrument.instrument_id} · {timeframe} · {window_hours}t · "
        f"siste close {latest_display}"
    )
    if forming is not None:
        age = forming_candle_event_age_seconds(forming)
        st.caption(
            f"● Forming candle · Saxo chart-stream · UI-only · oppdatert for {age:.1f} sek siden. "
            "Den inngår ikke i canonical historikk, indikatorer eller AutoManager-signaler."
        )

    fig = build_trading_desk_figure(
        market=market,
        timeframe=timeframe,
        window_hours=int(window_hours),
        primary=display_primary,
        overlays=loaded_overlays,
        overlay_mode=overlay_mode,
        indicators=technical,
        indicator_names=indicator_names,
        indicator_timeframes={INDICATOR_MACD: st.session_state[MACD_TIMEFRAME_STATE_KEY]},
        chart_height=chart_height,
        price_panel_share=price_panel_pct / 100.0,
    )
    if primary and INDICATOR_SWING_BANDS in indicator_names:
        add_swing_bands_to_figure(fig, primary)
    localize_plotly_figure_v2(fig)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"tradingdesk-live-chart:{market}",
    )

    if not primary:
        st.info(f"Fant ingen canonical 1m-bars for {market}, heller ikke rundt siste registrerte bar.")
    else:
        volume_points = sum(item.volume is not None for item in primary)
        if volume_points < len(primary):
            st.caption(
                "Volum vises bare der canonical bar har ekte Saxo chart-volume. "
                "Bars bygget kun fra quote-stream har foreløpig ikke markedsvolum; sample_count brukes aldri som volum."
            )


def _render_automanager_workspace() -> None:
    context = _load_active_context()
    st.divider()
    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.subheader(f"AutoManager · {market}")
        st.caption(
            "Forvaltning av det valgte canonical produktmandatet. LIVE og shadow bruker samme lukkede 30m-signalgrunnlag; "
            "Position Guardian/risk-laget kan fortsatt redusere eller lukke defensivt."
        )
    with header_right:
        st.page_link("pages/6_AutoTrader_POC.py", label="Full AutoTrader", icon="⚙️")
    if context is None:
        st.info("AutoManager venter på aktivt v2-workspace.")
        return
    with st.container(border=True):
        render_tradingdesk_automanage_panel_v2(context)
    render_tradingdesk_automanage_pnl_chart_v2(context)


with chart_column:
    if auto_refresh:
        analysis_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
        if analysis_fragment is not None:
            analysis_fragment(run_every=f"{V2_ANALYSIS_REFRESH_SECONDS}s")(_render_v2_analysis)()
        else:
            _render_v2_analysis()

        chart_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
        if chart_fragment is not None:
            try:
                forming = forming_store.load(market=market)
            except Exception:
                forming = None
            refresh_seconds = live_chart_refresh_seconds(forming)
            chart_fragment(run_every=f"{refresh_seconds}s")(_render_live_chart)()
        else:
            _render_live_chart()
    else:
        _render_v2_analysis()
        _render_live_chart()

    _render_automanager_workspace()
