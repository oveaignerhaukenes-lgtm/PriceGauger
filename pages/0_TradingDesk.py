from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import streamlit as st

from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2
from autotrader_v3_instance_controls_ui_v1 import render_v3_instance_controls_v1
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1
from build_info import render_build_badge
from companion_ui_v2 import render_companion_panel_v2
from indicator_guide_v1 import render_indicator_guide_v1
from realtime_market_data import RealtimeMarketDataStore
from saxo_chart_live import FormingCandle1m, FormingCandleStore, forming_candle_event_age_seconds
from time_display_v2 import oslo_label
from trading_desk import TIMEFRAME_MINUTES, resample_bars, utc
from trading_desk_chart import OVERLAY_ACTUAL, OVERLAY_NORMALIZED
from trading_desk_indicators import DEFAULT_INDICATORS, INDICATOR_OPTIONS
from trading_desk_v2_context import TradingDeskV2Context, load_trading_desk_contexts_v2
from tradingdesk_automanage_panel_v2 import render_tradingdesk_automanage_panel_v2, render_tradingdesk_automanage_pnl_chart_v2
from tradingdesk_ui.charts.lightweight.adapters import load_lightweight_trade_markers_v1
from tradingdesk_ui.charts.lightweight.direct_contract import build_lightweight_direct_live_payload_v1
from tradingdesk_ui.charts.lightweight.live_test_snapshot_v1 import load_live_test_snapshot_v1
from tradingdesk_three_trader_lab_v1 import render_tradingdesk_three_trader_lab_v1
from tradingdesk_ui.charts.lightweight.simple_live_v2 import render_lightweight_simple_live_v2
from tradingdesk_ui.charts.lightweight.toolbar import LIGHTWEIGHT_TIMEFRAMES_V1, render_lightweight_timeframe_toolbar_v1
from v2_forecast_visualization import V2_FORECAST_CSS, render_v2_forecast_chart, render_v2_technical_explanation

V2_ANALYSIS_REFRESH_SECONDS=60; LIVE_CANDLE_OVERLAY_REFRESH_SECONDS=1
TIMEFRAME_STATE_KEY='tradingdesk_timeframe'; AUTO_REFRESH_STATE_KEY='tradingdesk_auto_refresh'; MARKET_STATE_KEY='tradingdesk-v2-market'
CONTROLS_WIDTH_STATE_KEY='tradingdesk-controls-width-pct'; WINDOW_HOURS_STATE_KEY='tradingdesk-window-hours'; OVERLAY_MODE_STATE_KEY='tradingdesk-overlay-mode'
OVERLAYS_STATE_KEY='tradingdesk-overlays'; INDICATORS_STATE_KEY='tradingdesk-indicators'; CHART_HEIGHT_STATE_KEY='tradingdesk-chart-height'; PRICE_PANEL_PCT_STATE_KEY='tradingdesk-price-panel-pct'

st.set_page_config(page_title='TradingDesk · PriceGauger',page_icon='📊',layout='wide'); render_build_badge(); st.markdown(V2_FORECAST_CSS,unsafe_allow_html=True)
st.title('TradingDesk'); st.caption('Marked, live chart, SIM-sammenligning og kontroll av den valgte V3-instansen på ett sted.')
store=RealtimeMarketDataStore(); forming_store=FormingCandleStore()
try: baseline_contexts=load_trading_desk_contexts_v2()
except Exception as exc: st.warning(f'TradingDesk kunne ikke lese workspaces: {exc}'); st.stop()
available_markets=sorted(baseline_contexts)
if not available_markets: st.info('Venter på aktive workspaces.'); st.stop()
requested_market=str(st.query_params.get('market','') or '').strip()
if st.session_state.get(MARKET_STATE_KEY) not in available_markets: st.session_state[MARKET_STATE_KEY]=requested_market if requested_market in available_markets else available_markets[0]
if st.session_state.get(TIMEFRAME_STATE_KEY) not in TIMEFRAME_MINUTES: st.session_state[TIMEFRAME_STATE_KEY]='5m'
if AUTO_REFRESH_STATE_KEY not in st.session_state: st.session_state[AUTO_REFRESH_STATE_KEY]=True
for key,default in ((WINDOW_HOURS_STATE_KEY,24),(CHART_HEIGHT_STATE_KEY,780),(PRICE_PANEL_PCT_STATE_KEY,50),(CONTROLS_WIDTH_STATE_KEY,30)): st.session_state.setdefault(key,default)
st.session_state.setdefault(OVERLAY_MODE_STATE_KEY,OVERLAY_NORMALIZED); st.session_state.setdefault(OVERLAYS_STATE_KEY,[]); st.session_state.setdefault(INDICATORS_STATE_KEY,list(DEFAULT_INDICATORS))
timeframe=str(st.session_state[TIMEFRAME_STATE_KEY]); controls_width_pct=int(st.session_state[CONTROLS_WIDTH_STATE_KEY])
chart_column,controls_column=st.columns([100-controls_width_pct,controls_width_pct],gap='medium')
with controls_column:
    st.subheader('Kontroller')
    market=st.selectbox('Marked',available_markets,key=MARKET_STATE_KEY); st.query_params['market']=market
    baseline_context=baseline_contexts[market]; baseline_view=baseline_context.forecast
    horizons=tuple(sorted(int(v) for v in baseline_view.available_horizons)); selected_horizon=st.selectbox('Prognosehorisont',horizons,index=0,format_func=lambda s:f'{s//60}m' if s<3600 else f'{s/3600:g}t')
    use_interpreter=st.checkbox('Technical Interpreter',value=False,disabled=not baseline_view.interpreter_available)
    window_hours=st.selectbox('Grafvindu',[6,12,24,48],key=WINDOW_HOURS_STATE_KEY,format_func=lambda v:f'{v}t')
    indicator_names=st.multiselect('Indikatorer',list(INDICATOR_OPTIONS),key=INDICATORS_STATE_KEY)
    auto_refresh=st.toggle('Autooppdater',key=AUTO_REFRESH_STATE_KEY)
    st.slider('Kontrollpanel bredde',20,40,2,key=CONTROLS_WIDTH_STATE_KEY)

def _load_active_context():
    try: return load_trading_desk_contexts_v2(requested_horizons={market:int(selected_horizon)},interpreter_by_market={market:bool(use_interpreter)}).get(market)
    except Exception as exc: st.warning(f'Kunne ikke oppdatere context: {exc}'); return None

def _load_trade_markers():
    try: return tuple(load_lightweight_trade_markers_v1(market))
    except Exception as exc: st.warning(f'Handelspiler kunne ikke lastes: {exc}'); return ()

def _render_v2_analysis():
    context=_load_active_context()
    if context is None:return
    view=context.forecast; st.subheader('PriceGauger analyse'); st.markdown(f'<div class="pg-v2-layout">{render_v2_forecast_chart(view)}{render_v2_technical_explanation(view)}</div>',unsafe_allow_html=True)

def _load_chart_payload():
    context=baseline_contexts.get(market)
    if context is None or context.instrument is None:return None,(),None
    closed,forming=load_live_test_snapshot_v1(market=market,timeframe=timeframe,window_hours=window_hours,instrument=context.instrument)
    payload=build_lightweight_direct_live_payload_v1(market=market,timeframe=timeframe,primary=closed,overlays={},overlay_mode='Normalisert %',indicators=None,indicator_names=(),indicator_timeframes={},chart_height=360,price_panel_share=1.0,trade_markers=_load_trade_markers(),forming_candle=forming)
    return payload,closed,forming

def _render_live_chart(refresh_only=False):
    payload,closed,forming=_load_chart_payload()
    if payload is None:return
    render_lightweight_simple_live_v2(payload,key=f'tradingdesk-live:{market}:{timeframe}',refresh_only=refresh_only)

@st.fragment(run_every='1000ms')
def _tick(): _render_live_chart(refresh_only=True)

def _matching_v3_instances():
    try: return tuple(i for i in bootstrap_v3_instances_from_enrollments_v1() if i.market_name==market and i.enabled)
    except Exception as exc: st.warning(f'V3-instansregister utilgjengelig: {exc}'); return ()

with chart_column:
    st.subheader('Live chart'); render_lightweight_timeframe_toolbar_v1(state_key=TIMEFRAME_STATE_KEY); _render_live_chart(); _tick()
    st.fragment(run_every=f'{V2_ANALYSIS_REFRESH_SECONDS}s' if auto_refresh else None)(_render_v2_analysis)()
    st.divider(); st.subheader('SIM → velg LIVE-strategi')
    st.caption('Sammenlign strategiene på samme marked, og endre deretter den aktuelle V3-instansen direkte her. Valget lagres i instansens canonical config.')
    with st.expander('SIM · Strategy Lab og P/L',expanded=True):
        render_tradingdesk_three_trader_lab_v1(baseline_context)
    instances=_matching_v3_instances()
    if instances:
        ids=tuple(i.instance_id for i in instances); by_id={i.instance_id:i for i in instances}
        selected=st.selectbox('Autotrader-instans',ids,format_func=lambda x:f'{by_id[x].account_id} · {by_id[x].market_name}',key=f'td-v3-instance:{market}')
        with st.container(border=True): render_v3_instance_controls_v1(by_id[selected],key_prefix='tradingdesk',compact=True)
    else: st.info('Ingen V3-instans er knyttet til dette markedet ennå.')
    st.divider(); st.subheader('AutoManager / execution')
    context=_load_active_context()
    if context is not None:
        with st.container(border=True): observations=render_tradingdesk_automanage_panel_v2(context,auto_refresh=auto_refresh)
        render_tradingdesk_automanage_pnl_chart_v2(context,observations=observations,auto_refresh=auto_refresh)
