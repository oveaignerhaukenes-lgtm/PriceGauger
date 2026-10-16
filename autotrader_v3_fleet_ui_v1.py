from __future__ import annotations

import pandas as pd
import streamlit as st
from autotrader_execution_diagnostics_v1 import load_execution_diagnostic_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_control_plane_v1 import authority_state_v3
from autotrader_v3_execution_policy_v1 import load_execution_policy_v3
from autotrader_v3_instance_controls_ui_v1 import render_v3_instance_controls_v1
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_registry_v1 import strategy_display_label_v3
from database import connect


def _runtime(instance_id):
    try:
        with connect() as db: row=db.execute('SELECT status,detail,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?',(instance_id,)).fetchone()
        if row is None:return ('NO HEARTBEAT','',None)
        g=lambda k,n:row[k] if isinstance(row,dict) else row[n]; return str(g('status',0)),str(g('detail',1) or ''),g('updated_at',2)
    except Exception as exc:return ('UNKNOWN',str(exc),None)

def _avoid_loss_monitor(instance_id):
    """Read the independent protective-stop health, not generic V3 READY."""
    try:
        with connect() as db:
            row=db.execute(
                "SELECT status,detail,updated_at FROM autotrader_v3_avoid_loss_monitor_v1 "
                "WHERE trader_id=?",(instance_id,)).fetchone()
        if row is None:return ("UNPROTECTED","Risikoløkken har ikke bekreftet Saxo-data",None)
        return (str(row["status"]),str(row["detail"]),str(row["updated_at"]))
    except Exception:
        return ("UNPROTECTED","Risikostatus ikke tilgjengelig",None)


def _event_count(instance_id):
    try:
        with connect() as db: row=db.execute("SELECT count(*) AS n FROM autotrader_v3_execution_events WHERE instance_id=? AND executed_at>=now()-INTERVAL '24 hours'",(instance_id,)).fetchone()
        return int(row['n'] if isinstance(row,dict) else row[0])
    except Exception:return 0

def render_v3_fleet_management_v1():
    instances=bootstrap_v3_instances_from_enrollments_v1()
    if not instances: st.info('Ingen V3-instanser finnes ennå.'); return
    broker=configured_live_pilot_client_v3(); rows=[]; account_names={}
    if broker:
        try:
            for row in broker.accounts():
                if isinstance(row,dict):
                    aid=str(row.get('AccountId') or '').strip()
                    if aid:account_names[aid]=str(row.get('AccountName') or row.get('DisplayName') or '').strip()
        except Exception: pass
    for item in instances:
        config=load_autotrader_config_v3(item.instance_id); policy=load_execution_policy_v3(item.instance_id); auth=authority_state_v3(item.instance_id); status,detail,updated=_runtime(item.instance_id)
        try: pnl=broker.open_pnl_exact(account_id=item.account_id,uic=item.uic,asset_type=item.asset_type) if broker else None
        except Exception: pnl=None
        rows.append((item,config,policy,auth,status,detail,updated,pnl,_event_count(item.instance_id)))
    st.subheader('V3 Fleet'); st.caption('Samlet oversikt over aktive autotradere. TradingDesk er den raske arbeidsflaten for én instans; begge bruker samme canonical config. Handler 24t inkluderer også handler før eventuelle strategibytter.')
    m=st.columns(4); m[0].metric('Instanser',len(rows)); m[1].metric('LIVE',sum(r[3].live_armed for r in rows)); m[2].metric('SIM',sum(r[3].sim_armed for r in rows)); m[3].metric('Handler 24t',sum(r[8] for r in rows))
    comparable=[{'Instans':f'{r[0].market_name} · {account_names.get(r[0].account_id) or r[0].account_id}','Åpen P/L':float(r[7])} for r in rows if r[7] is not None]
    if comparable:
        st.markdown('**Relativ prestasjon · nåværende åpne P/L**')
        st.bar_chart(pd.DataFrame(comparable).set_index('Instans'))
        st.caption('Dette er brokerens nåværende åpne P/L per eksakt konto/instrument, ikke en rekonstruert historisk avkastningskurve.')
    for item,config,policy,auth,status,detail,updated,pnl,count in rows:
        with st.container(border=True):
            account_name=account_names.get(item.account_id,''); account_title=account_name or item.account_id
            active_label=strategy_display_label_v3(config.strategy_key,config.timeframe,config.regime_timeframe)
            # Streamlit st.metric truncates values with CSS ellipsis in narrow
            # columns. Strategy labels (R/S timeframes and variants) must be
            # readable in full, even on mobile; render in a separate full-width
            # text row instead of squeezing them into a metric value.
            c=st.columns([2,1,1,1])
            c[0].markdown(f'### {account_title} · {item.market_name}')
            c[1].metric('LIVE','ON' if auth.live_armed else 'OFF')
            c[2].metric('Åpen P/L','—' if pnl is None else f'{pnl:+.2f}')
            c[3].metric('Handler 24t',count)
            st.markdown(f'**Strategi:** {active_label}')
            st.caption(f'V3 {item.instance_id[:8]} · konto {item.account_id} · UIC {item.uic} · {item.asset_type} · instrument {item.instrument_id}')
            cap=f'{policy.max_notional_nok:,.0f} NOK' if policy else 'ikke satt'; st.caption(f'{status} · {detail} · aktiv {active_label} · options {", ".join(config.modifiers) or "ingen"} · ramme {cap}')
            if config.strategy_key=="avoid-loss-v1":
                stop_status,stop_detail,stop_updated=_avoid_loss_monitor(item.instance_id)
                if stop_status=="PROTECTED":
                    st.success("Unngå tap · Saxo-risikokontroll aktiv. "+stop_detail)
                elif stop_status=="FLAT":
                    st.info("Unngå tap · FLAT. "+stop_detail)
                elif stop_status in {"STOP_PENDING","PENDING"}:
                    st.warning("Unngå tap · "+stop_status+" · "+stop_detail)
                else:
                    st.error("UNPROTECTED: Ingen verifisert aktiv −1 %-stop! "+stop_detail)
                st.caption("Siste kontroll: "+str(stop_updated or "ukjent"))
            try:
                d=load_execution_diagnostic_v1(account_id=item.account_id,uic=int(item.uic),asset_type=item.asset_type,owner_key=item.instance_id,engine_id='V3')
                if d.request_state: st.caption(f'Execution: {d.request_state} · {d.request_detail or ""}')
            except Exception: pass
            with st.expander('Administrer instansen',expanded=False): render_v3_instance_controls_v1(item,key_prefix='fleet')

def render_autotrader_v3_fleet_preview(rows):
    st.subheader('AutoTrader v3 · Fleet')
    for row in rows:
        with st.container(border=True): st.markdown(row.truth_line)

__all__=['render_v3_fleet_management_v1','render_autotrader_v3_fleet_preview']
