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
from database import connect


def _runtime(instance_id):
    try:
        with connect() as db: row=db.execute('SELECT status,detail,updated_at FROM autotrader_v3_live_runtime_state WHERE trader_id=?',(instance_id,)).fetchone()
        if row is None:return ('NO HEARTBEAT','',None)
        g=lambda k,n:row[k] if isinstance(row,dict) else row[n]; return str(g('status',0)),str(g('detail',1) or ''),g('updated_at',2)
    except Exception as exc:return ('UNKNOWN',str(exc),None)

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
    st.subheader('V3 Fleet'); st.caption('Samlet oversikt over aktive autotradere. TradingDesk er den raske arbeidsflaten for én instans; begge bruker samme canonical config.')
    m=st.columns(4); m[0].metric('Instanser',len(rows)); m[1].metric('LIVE',sum(r[3].live_armed for r in rows)); m[2].metric('SIM',sum(r[3].sim_armed for r in rows)); m[3].metric('Handler 24t',sum(r[8] for r in rows))
    comparable=[{'Instans':f'{r[0].market_name} · {account_names.get(r[0].account_id) or r[0].account_id}','Åpen P/L':float(r[7])} for r in rows if r[7] is not None]
    if comparable:
        st.markdown('**Relativ prestasjon · nåværende åpne P/L**')
        st.bar_chart(pd.DataFrame(comparable).set_index('Instans'))
        st.caption('Dette er brokerens nåværende åpne P/L per eksakt konto/instrument, ikke en rekonstruert historisk avkastningskurve.')
    for item,config,policy,auth,status,detail,updated,pnl,count in rows:
        with st.container(border=True):
            account_name=account_names.get(item.account_id,''); account=f'{account_name} ({item.account_id})' if account_name else item.account_id
            c=st.columns([2,1,1,1,1]); c[0].markdown(f'### {item.market_name} · {account}'); c[1].metric('Strategi',config.strategy_key); c[2].metric('LIVE','ON' if auth.live_armed else 'OFF'); c[3].metric('Åpen P/L','—' if pnl is None else f'{pnl:+.2f}'); c[4].metric('Handler 24t',count)
            st.caption(f'V3 {item.instance_id[:8]} · konto {item.account_id} · UIC {item.uic} · {item.asset_type} · instrument {item.instrument_id}')
            cap=f'{policy.max_notional_nok:,.0f} NOK' if policy else 'ikke satt'; st.caption(f'{status} · {detail} · periode {config.timeframe} · options {", ".join(config.modifiers) or "ingen"} · ramme {cap}')
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
