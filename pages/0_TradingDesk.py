from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2
from build_info import render_build_badge
from companion_ui_v2 import render_companion_panel_v2
from indicator_guide_v1 import render_indicator_guide_v1
from realtime_market_data import RealtimeMarketDataStore
from saxo_chart_live import (
    FormingCandle1m,
    FormingCandleStore,
    forming_candle_event_age_seconds,
)
from time_display_v2 import oslo_label
from trading_desk import TIMEFRAME_MINUTES, last_available_window, resample_bars, utc
from trading_desk_chart import OVERLAY_ACTUAL, OVERLAY_NORMALIZED
from trading_desk_indicators import (
    DEFAULT_INDICATORS,
    INDICATOR_MACD,
    INDICATOR_OPTIONS,
    INDICATOR_VWAP,
    INDICATOR_WARMUP_PERIODS,
    calculate_indicators,
    clip_indicators,
)
from trading_desk_v2_context import TradingDeskV2Context, load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import (
    render_tradingdesk_automanage_panel_v2,
    render_tradingdesk_automanage_pnl_chart_v2,
)
from tradingdesk_ui.charts.lightweight.adapters import load_lightweight_trade_markers_v1
from tradingdesk_ui.charts.lightweight.direct_contract import (
    build_lightweight_direct_live_payload_v1,
)
from tradingdesk_ui.charts.lightweight.simple_live_v2 import render_lightweight_simple_live_v2
from tradingdesk_ui.charts.lightweight.toolbar import (
    LIGHTWEIGHT_TIMEFRAMES_V1,
    render_lightweight_timeframe_toolbar_v1,
)
from v2_forecast_visualization import (
    V2_FORECAST_CSS,
    render_v2_forecast_chart,
    render_v2_technical_explanation,
)


V2_ANALYSIS_REFRESH_SECONDS = 60
LIVE_CHART_BASE_REFRESH_SECONDS = 5
LIVE_CANDLE_OVERLAY_REFRESH_SECONDS = 1
TRADINGDESK_PAGE_REFRESH_SECONDS = 2
QUICK_TIMEFRAMES = LIGHTWEIGHT_TIMEFRAMES_V1
TIMEFRAME_STATE_KEY = "tradingdesk_timeframe"
AUTO_REFRESH_STATE_KEY = "tradingdesk_auto_refresh"
MARKET_STATE_KEY = "tradingdesk-v2-market"
CONTROLS_WIDTH_STATE_KEY = "tradingdesk-controls-width-pct"
WINDOW_HOURS_STATE_KEY = "tradingdesk-window-hours"
OVERLAY_MODE_STATE_KEY = "tradingdesk-overlay-mode"
OVERLAYS_STATE_KEY = "tradingdesk-overlays"
INDICATORS_STATE_KEY = "tradingdesk-indicators"
CHART_HEIGHT_STATE_KEY = "tradingdesk-chart-height"
PRICE_PANEL_PCT_STATE_KEY = "tradingdesk-price-panel-pct"


st.set_page_config(page_title="TradingDesk · PriceGauger", page_icon="📊", layout="wide")
render_build_badge()
st.markdown(V2_FORECAST_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <style>
    div[data-testid="stMainBlockContainer"], .block-container {
        max-width: 100% !important;
        padding-left: 1.25rem !important;
        padding-right: 1.25rem !important;
    }
    div[data-testid="stPlotlyChart"] .modebar {
        top: .35rem !important;
        right: .35rem !important;
        flex-direction: row !important;
        background: rgba(255,255,255,.94) !important;
        border: 1px solid rgba(17,24,39,.16) !important;
        border-radius: .45rem !important;
        padding: .18rem !important;
    }
    div[data-testid="stPlotlyChart"] .modebar-group {
        display: flex !important;
        flex-direction: row !important;
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
if AUTO_REFRESH_STATE_KEY not in st.session_state:
    st.session_state[AUTO_REFRESH_STATE_KEY] = True
try:
    controls_width_pct = int(st.session_state.get(CONTROLS_WIDTH_STATE_KEY, 30))
except (TypeError, ValueError):
    controls_width_pct = 30
if not 20 <= controls_width_pct <= 40:
    controls_width_pct = 30
st.session_state[CONTROLS_WIDTH_STATE_KEY] = controls_width_pct

if st.session_state.get(WINDOW_HOURS_STATE_KEY) not in {6, 12, 24, 48}:
    st.session_state[WINDOW_HOURS_STATE_KEY] = 24
if st.session_state.get(OVERLAY_MODE_STATE_KEY) not in {OVERLAY_NORMALIZED, OVERLAY_ACTUAL}:
    st.session_state[OVERLAY_MODE_STATE_KEY] = OVERLAY_NORMALIZED
if OVERLAYS_STATE_KEY not in st.session_state or not isinstance(
    st.session_state.get(OVERLAYS_STATE_KEY), (list, tuple)
):
    st.session_state[OVERLAYS_STATE_KEY] = []
if INDICATORS_STATE_KEY not in st.session_state or not isinstance(
    st.session_state.get(INDICATORS_STATE_KEY), (list, tuple)
):
    st.session_state[INDICATORS_STATE_KEY] = list(DEFAULT_INDICATORS)
try:
    persisted_chart_height = int(st.session_state.get(CHART_HEIGHT_STATE_KEY, 780))
except (TypeError, ValueError):
    persisted_chart_height = 780
if not 360 <= persisted_chart_height <= 1200:
    persisted_chart_height = 780
st.session_state[CHART_HEIGHT_STATE_KEY] = persisted_chart_height
try:
    persisted_price_panel_pct = int(st.session_state.get(PRICE_PANEL_PCT_STATE_KEY, 50))
except (TypeError, ValueError):
    persisted_price_panel_pct = 50
if not 40 <= persisted_price_panel_pct <= 65:
    persisted_price_panel_pct = 50
st.session_state[PRICE_PANEL_PCT_STATE_KEY] = persisted_price_panel_pct

timeframe = str(st.session_state[TIMEFRAME_STATE_KEY])


def _persist_market_selection() -> None:
    selected = str(st.session_state.get(MARKET_STATE_KEY, "") or "")
    if selected in available_markets:
        st.query_params["market"] = selected


def _horizon_label(seconds: int) -> str:
    value = int(seconds)
    if value < 3600:
        return f"{value // 60:g}m"
    hours = value / 3600.0
    if abs(hours - 168.0) <= 1e-6:
        return "7d"
    return f"{hours:g}t"


chart_column, controls_column = st.columns([100 - controls_width_pct, controls_width_pct], gap="medium")

with controls_column:
    st.subheader("Kontroller")
    st.slider(
        "Bredde på kontrollpanel",
        min_value=20,
        max_value=40,
        step=2,
        key=CONTROLS_WIDTH_STATE_KEY,
        help="Andel av TradingDesk-bredden som reserveres til høyre kontrollpanel. Endringen gjelder ved neste rerun.",
    )

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

        if baseline_context.instrument is None:
            st.warning("Ingen aktiv/subscribed v2-instrumentkilde. Chart og AutoManager er deaktivert for markedet.")

    with st.expander("Graf", expanded=True):
        window_hours = st.selectbox(
            "Vindu",
            [6, 12, 24, 48],
            key=WINDOW_HOURS_STATE_KEY,
            format_func=lambda value: f"{value}t",
        )
        overlay_mode = st.radio(
            "Overlay-akse",
            [OVERLAY_NORMALIZED, OVERLAY_ACTUAL],
            key=OVERLAY_MODE_STATE_KEY,
        )

        overlay_options = [
            item
            for item in available_markets
            if item != market and baseline_contexts[item].instrument is not None
        ]
        safe_overlays = [
            item
            for item in st.session_state.get(OVERLAYS_STATE_KEY, [])
            if item in overlay_options
        ]
        if list(st.session_state.get(OVERLAYS_STATE_KEY, [])) != safe_overlays:
            st.session_state[OVERLAYS_STATE_KEY] = safe_overlays
        overlays = st.multiselect(
            "Sammenlign med",
            overlay_options,
            key=OVERLAYS_STATE_KEY,
        )

    with st.expander("Indikatorer", expanded=True):
        safe_indicators = [
            item
            for item in st.session_state.get(INDICATORS_STATE_KEY, [])
            if item in INDICATOR_OPTIONS
        ]
        if list(st.session_state.get(INDICATORS_STATE_KEY, [])) != safe_indicators:
            st.session_state[INDICATORS_STATE_KEY] = safe_indicators
        indicator_names = st.multiselect(
            "Vis indikatorer",
            list(INDICATOR_OPTIONS),
            key=INDICATORS_STATE_KEY,
            help=(
                "Bollinger/EMA/SMA/VWAP og Swing high/low ligger på prisgrafen. MACD, RSI, Stochastic og ATR får egne paneler. "
                "VWAP er volumvektet over det viste chart-vinduet. Swing-sonene er bekreftede lokale pivoter og er kun en teknisk visualisering."
            ),
        )

        chart_height = st.slider(
            "Total grafhøyde",
            min_value=360,
            max_value=1200,
            step=20,
            key=CHART_HEIGHT_STATE_KEY,
            help="Squash eller strekk hele chart-stacken uten å endre data eller indikatorberegning.",
        )
        price_panel_pct = st.slider(
            "Hovedgrafens andel",
            min_value=40,
            max_value=65,
            step=5,
            key=PRICE_PANEL_PCT_STATE_KEY,
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
                f"Ett chart-iframe eier canonical bars og forming candle. TradingDesk leser "
                f"forming candle hvert {LIVE_CANDLE_OVERLAY_REFRESH_SECONDS}. sekund; canonical data følger samme chart-runtime. "
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


def _load_trade_markers() -> tuple:
    try:
        return tuple(load_lightweight_trade_markers_v1(market))
    except Exception:
        return ()


def _render_v2_analysis(*, include_companion: bool = True) -> None:
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

    if include_companion:
        render_companion_panel_v2(view)


def _render_v2_analysis_snapshot() -> None:
    """Refresh read-only analysis without recreating companion controls."""
    _render_v2_analysis(include_companion=False)


def _render_companion_workspace() -> None:
    context = _load_active_context()
    if context is not None:
        render_companion_panel_v2(context.forecast)


def _render_live_chart_controls() -> None:
    """Render stable chart controls outside the timed chart fragment."""
    st.subheader("Live chart")
    render_lightweight_timeframe_toolbar_v1(state_key=TIMEFRAME_STATE_KEY)


def _recent_forming_candle(context: TradingDeskV2Context | None):
    if context is None or context.instrument is None:
        return None
    try:
        candidate = forming_store.load(market=market)
    except Exception:
        return None
    if (
        candidate is not None
        and str(candidate.uic) == str(context.instrument.provider_instrument_id)
        and candidate.asset_type == context.instrument.asset_type
        and (forming_candle_event_age_seconds(candidate) or 0.0) <= 8.0
    ):
        return candidate
    return None


def _forming_chart_candle(context: TradingDeskV2Context | None) -> FormingCandle1m | None:
    """Aggregate the fresh 1m presentation candle into the selected chart bucket."""

    candidate = _recent_forming_candle(context)
    if candidate is None:
        return None
    minutes = int(TIMEFRAME_MINUTES[timeframe])
    if minutes <= 1:
        return candidate

    current_at = utc(candidate.bar_time)
    bucket_seconds = minutes * 60
    bucket_epoch = int(current_at.timestamp()) - (int(current_at.timestamp()) % bucket_seconds)
    bucket_at = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
    try:
        closed_1m = tuple(
            item
            for item in store.load_range(
                market=market,
                start=bucket_at,
                end=current_at,
                limit=max(4, minutes + 2),
            )
            if bucket_at <= utc(item.bar_time) < current_at
        )
    except Exception:
        closed_1m = ()

    open_price = float(closed_1m[0].open) if closed_1m else float(candidate.open)
    highs = [float(item.high) for item in closed_1m] + [float(candidate.high)]
    lows = [float(item.low) for item in closed_1m] + [float(candidate.low)]
    volumes = [float(item.volume) for item in closed_1m if item.volume is not None]
    if candidate.volume is not None:
        volumes.append(float(candidate.volume))

    return FormingCandle1m(
        market=candidate.market,
        bar_time=bucket_at.isoformat(),
        open=open_price,
        high=max(highs),
        low=min(lows),
        close=float(candidate.close),
        volume=sum(volumes) if volumes else None,
        provider=candidate.provider,
        uic=int(candidate.uic),
        asset_type=candidate.asset_type,
        symbol=candidate.symbol,
        delayed_by_minutes=candidate.delayed_by_minutes,
        source_event_at=candidate.source_event_at,
        updated_at=candidate.updated_at,
    )


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
            if INDICATOR_VWAP in indicator_names:
                technical = replace(technical, vwap=calculate_indicators(primary).vwap)
        except ValueError as exc:
            st.warning(f"Kunne ikke beregne tekniske indikatorer for {market}: {exc}")

    latest_display = "ingen data"
    if primary:
        latest_display = f"{primary[-1].close:g} @ {oslo_label(primary[-1].bar_time)}"

    st.caption(f"**{market}** · v2 instrument_id {context.instrument.instrument_id}")
    st.caption(f"{timeframe} · {window_hours}t · siste close {latest_display}")

    # Canonical storage contains CLOSED 1m bars only.  A timed rerun cannot make the
    # current 5m candle move unless we also project the presentation-only forming
    # candle from the live Saxo stream into the selected timeframe.
    forming = _forming_chart_candle(context)

    payload = build_lightweight_direct_live_payload_v1(
        market=market,
        timeframe=timeframe,
        primary=primary,
        overlays=loaded_overlays,
        overlay_mode=overlay_mode,
        indicators=technical,
        indicator_names=indicator_names,
        indicator_timeframes={INDICATOR_MACD: timeframe},
        chart_height=chart_height,
        price_panel_share=price_panel_pct / 100.0,
        # Reload marker projection on every live fragment tick.  The adapter cache is
        # intentionally short, so newly reconciled AutoTrader OPEN/CLOSE and manual
        # Saxo fills become visible without a full-page reload.
        trade_markers=_load_trade_markers(),
        forming_candle=forming,
    )

    if indicator_names:
        chart_surface, indicator_surface = st.columns([4.4, 1.35], gap="small")
    else:
        chart_surface, indicator_surface = st.container(), None
    with chart_surface:
        render_lightweight_simple_live_v2(
            payload,
            key=f"tradingdesk-lightweight-simple-v2:{market}",
        )
        st.caption(
            "Lightweight Charts · canonical closed bars + live forming candle, valgte indikatorer og AutoTrader-markører. "
            "Dra for pan og bruk pinch/hjul for zoom."
        )
    if indicator_surface is not None:
        with indicator_surface:
            view = context.forecast
            render_indicator_guide_v1(
                st,
                indicator_names=indicator_names,
                technical=technical,
                latest_close=None if not primary else float(primary[-1].close),
                trend_state=view.trend_state,
                momentum_state=view.momentum_state,
                volatility_state=view.volatility_state,
                structure_state=view.structure_state,
                ai_summary=(view.interpreter_summary if use_interpreter else None),
            )

    if not primary:
        st.info(f"Fant ingen canonical 1m-bars for {market}, heller ikke rundt siste registrerte bar.")
    else:
        volume_points = sum(item.volume is not None for item in primary)
        if volume_points < len(primary):
            st.caption(
                "Volum og VWAP bruker bare bars der canonical bar har ekte Saxo chart-volume. "
                "Bars bygget kun fra quote-stream har foreløpig ikke markedsvolum; sample_count brukes aldri som volum."
            )


def _render_automanager_workspace() -> None:
    context = _load_active_context()
    st.divider()
    header_left, header_right = st.columns([5, 1])
    with header_left:
        st.subheader(f"AutoManager · {market}")
        st.caption(
            "Forvaltning av det valgte canonical produktmandatet. Hver strategi beholder sitt eksplisitte "
            "signalhierarki og sin egen signal-clock; Position Guardian/risk-laget kan fortsatt redusere eller lukke defensivt."
        )
    with header_right:
        st.page_link("pages/6_AutoTrader_POC.py", label="Full AutoTrader", icon="⚙️")
    available_live = " · ".join(item.label for item in AUTOTRADER_STRATEGIES_V2)
    st.caption(f"Tilgjengelige LIVE-strategier: {available_live}")
    st.info(
        "Feltet «LIVE-pilot» under execution viser bare piloter som allerede er aktive. "
        "Selve strategivalget ligger i AutoManager-kortet under åpen posisjon; MTF 30/10/5 er nå et LIVE-kapabelt alternativ der."
    )
    if context is None:
        st.info("AutoManager venter på aktivt v2-workspace.")
        return
    with st.container(border=True):
        observations = render_tradingdesk_automanage_panel_v2(context)
    render_tradingdesk_automanage_pnl_chart_v2(context, observations=observations)


# Deliberately use a whole-script rerun here, not a Streamlit fragment.
# TradingDesk needs one shared refresh boundary while we verify the live chart
# end-to-end; fragment isolation previously allowed the visible page/chart to
# remain stale while the backend stream kept advancing.
if auto_refresh:
    st_autorefresh(
        interval=TRADINGDESK_PAGE_REFRESH_SECONDS * 1000,
        limit=None,
        key="tradingdesk-full-page-refresh-v1",
    )

with chart_column:
    _render_v2_analysis()
    _render_live_chart_controls()
    _render_live_chart()
    _render_automanager_workspace()
