from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from autotrader_execution_context_v2 import AutoTraderExecutionContextV2
from build_info import render_build_badge
from companion_ui_v2 import render_companion_panel_v2
from realtime_market_data import RealtimeMarketDataStore
from time_display_v2 import localize_plotly_figure_v2, oslo_label
from trading_desk import TIMEFRAME_MINUTES, last_available_window, resample_bars
from trading_desk_chart import (
    OVERLAY_ACTUAL,
    OVERLAY_NORMALIZED,
    build_trading_desk_figure,
)
from trading_desk_indicators import (
    DEFAULT_INDICATORS,
    INDICATOR_OPTIONS,
    INDICATOR_SWING_BANDS,
    INDICATOR_WARMUP_PERIODS,
    calculate_indicators,
    clip_indicators,
)
from trading_desk_product_panel import render_saxo_product_panel
from trading_desk_swing_bands import add_swing_bands_to_figure
from trading_desk_v2_context import TradingDeskV2Context, load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import render_tradingdesk_automanage_panel_v2
from v2_forecast_visualization import (
    V2_FORECAST_CSS,
    render_v2_forecast_chart,
    render_v2_technical_explanation,
)


LIVE_CHART_REFRESH_SECONDS = 30
V2_ANALYSIS_REFRESH_SECONDS = 60
QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m", "1h")
TIMEFRAME_STATE_KEY = "tradingdesk_timeframe"
AUTO_REFRESH_STATE_KEY = "tradingdesk_auto_refresh"


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

if st.session_state.get(TIMEFRAME_STATE_KEY) not in TIMEFRAME_MINUTES:
    st.session_state[TIMEFRAME_STATE_KEY] = "5m"
if AUTO_REFRESH_STATE_KEY not in st.session_state:
    st.session_state[AUTO_REFRESH_STATE_KEY] = False


def _select_timeframe(value: str) -> None:
    st.session_state[TIMEFRAME_STATE_KEY] = value


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
        market = st.selectbox("Marked", available_markets, key="tradingdesk-v2-market")
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
            st.warning("Ingen aktiv/subscribed v2-instrumentkilde. Chart og hurtighandel er deaktivert for markedet.")
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

    with st.expander(f"Handel · {market}", expanded=False):
        if baseline_context.instrument is None:
            st.warning("Hurtighandel krever eksplisitt v2-instrumentidentitet og er derfor deaktivert.")
        else:
            execution_context_v2 = AutoTraderExecutionContextV2.from_source(
                market_id=baseline_context.market_id,
                market_name=baseline_context.market_name,
                source=baseline_context.instrument,
            )
            st.caption(
                "Produktvalg er separat fra analyse/feed-instrumentet, men enhver TradingDesk-ordre bindes nå til "
                "den eksakte canonical v2-identiteten og revalideres før pre-check og submit."
            )
            render_saxo_product_panel(
                market,
                execution_context_v2=execution_context_v2,
            )
            st.page_link("pages/6_AutoTrader_POC.py", label="Åpne full AutoTrader", icon="🧪")

    with st.expander(f"AutoManage · {market}", expanded=True):
        render_tradingdesk_automanage_panel_v2(baseline_context)

    with st.expander("Status", expanded=False):
        auto_refresh = st.toggle(
            "Auto-oppdater TradingDesk",
            key=AUTO_REFRESH_STATE_KEY,
            help=(
                "Av som standard for å unngå at Streamlit rerenderer og gråer ut analyse/graf mens du leser. "
                "Når aktivert oppdateres chart rolig hvert 30. sekund og analyse hvert 60. sekund."
            ),
        )
        if auto_refresh:
            st.caption(
                f"Canonical chart-bars oppdateres hvert {LIVE_CHART_REFRESH_SECONDS}. sekund. "
                f"V2 workspace/health/TA Analyst oppdateres hvert {V2_ANALYSIS_REFRESH_SECONDS}. sekund."
            )
        else:
            st.caption("Auto-oppdatering er av. Siden oppdateres ved brukerhandling eller nettleser-refresh.")
        st.caption(
            "Chartet og v2-runtime konsumerer canonical 1m-data. Kjent Saxo-forsinkelse vises eksplisitt og regnes ikke som feed-feil når strømmen ellers er konsistent."
        )


def _load(name: str, *, range_start: datetime, range_end: datetime, limit: int = 10000):
    raw = store.load_range(market=name, start=range_start, end=range_end, limit=limit)
    return resample_bars(raw, timeframe=timeframe)


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
        except ValueError as exc:
            st.warning(f"Kunne ikke beregne tekniske indikatorer for {market}: {exc}")

    latest_display = "ingen data"
    if primary:
        latest_display = f"{primary[-1].close:g} @ {oslo_label(primary[-1].bar_time)}"

    st.subheader("Live chart")
    st.caption(
        f"**{market}** · v2 instrument_id {context.instrument.instrument_id} · {timeframe} · {window_hours}t · "
        f"siste close {latest_display}"
    )

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


with chart_column:
    if auto_refresh:
        analysis_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
        if analysis_fragment is not None:
            analysis_fragment(run_every=f"{V2_ANALYSIS_REFRESH_SECONDS}s")(_render_v2_analysis)()
        else:
            _render_v2_analysis()

        chart_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
        if chart_fragment is not None:
            chart_fragment(run_every=f"{LIVE_CHART_REFRESH_SECONDS}s")(_render_live_chart)()
        else:
            _render_live_chart()
    else:
        _render_v2_analysis()
        _render_live_chart()
