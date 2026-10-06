from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import streamlit as st

from autotrader_health_v1 import load_autotrader_health_snapshot_v1


_WIDGET_JS = r"""
export default function(component) {
  const {data,parentElement}=component, p=data.payload||{};
  const id='pg-at-health-v1', store='pg-at-alert-v1';
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const pnl=v=>Number.isFinite(Number(v))?`${Number(v)>=0?'+':''}${Number(v).toFixed(2)}`:'—';
  const age=v=>Number(v)<60?`${Math.round(Number(v))} s`:`${(Number(v)/60).toFixed(1)} min`;
  const when=v=>{try{return v?new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(v)):'—'}catch(_){return String(v||'—')}};
  let root=document.getElementById(id);
  if(!root){root=document.createElement('div');root.id=id;document.body.appendChild(root)}
  const state=String(p.state||'IDLE').toLowerCase();
  const rows=Array.from(p.instances||[]).map(x=>`
    <div class="row">
      <div><span class="dot ${String(x.severity||'IDLE').toLowerCase()}"></span><b>${esc(x.market_name)}</b><span class="right">${x.live_armed?'LIVE':(x.sim_armed?'SIM':'AV')}</span></div>
      <small>${esc(x.account_name||x.account_id)} · ${esc(x.runtime_status)} · P/L ${esc(pnl(x.open_pnl))}</small>
      <small>Sist ${esc(when(x.runtime_updated_at))} · Handler 24t ${esc(x.trades_24h)}</small>
      ${x.pending_state?`<small class="warn">Ordre ${esc(x.pending_state)} · ${esc(age(x.pending_age_seconds))}${x.broker_order_id?` · Saxo ${esc(x.broker_order_id)}`:''}</small>`:''}
      ${x.issue_message?`<small class="err">${esc(x.issue_message)}</small>`:''}
    </div>`).join('');
  const critical=Array.from(p.critical_messages||[]);
  root.innerHTML=`
    <style>
    #${id}{font-family:system-ui,sans-serif}#${id} button{font:inherit}
    #${id} .fab{position:fixed;right:14px;bottom:14px;z-index:1000001;width:48px;height:48px;border-radius:50%;border:3px solid white;color:white;font-weight:800;font-size:20px;box-shadow:0 4px 18px #0005;cursor:pointer}
    #${id} .green{background:#22c55e}#${id} .yellow{background:#f59e0b}#${id} .red{background:#ef4444}#${id} .idle{background:#64748b}
    #${id} .panel{position:fixed;right:14px;bottom:72px;z-index:1000000;width:min(420px,calc(100vw - 28px));max-height:70vh;overflow:auto;display:none;background:#fff;color:#111827;border:1px solid #94a3b866;border-radius:14px;padding:12px;box-shadow:0 14px 40px #0005}
    #${id} .panel.open{display:block}#${id} h3{margin:0 0 4px}#${id} .summary{font-size:12px;margin-bottom:8px;opacity:.72}
    #${id} .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}#${id} .stat{text-align:center;border:1px solid #94a3b844;border-radius:8px;padding:6px;font-size:10px}#${id} .stat b{display:block;font-size:14px}
    #${id} .row{border:1px solid #94a3b844;border-radius:9px;padding:8px;margin-top:7px;font-size:12px}#${id} small{display:block;margin-top:3px;overflow-wrap:anywhere}#${id} .right{float:right}#${id} .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
    #${id} .warn{color:#b45309}#${id} .err{color:#dc2626;font-weight:650}
    #${id} .back{position:fixed;inset:0;z-index:1000003;display:none;background:#0f172a66;align-items:center;justify-content:center;padding:16px}#${id} .back.open{display:flex}
    #${id} .alert{width:min(500px,calc(100vw - 28px));background:#fff;color:#111827;border:2px solid #ef4444;border-radius:14px;padding:16px;box-shadow:0 18px 55px #0006}#${id} .msg{margin:8px 0;padding:7px;border-left:4px solid #ef4444;background:#ef444411}
    #${id} .actions{text-align:right;margin-top:12px}#${id} .actions button{margin-left:6px;padding:7px 10px;border-radius:8px;border:1px solid #94a3b8;background:#fff;cursor:pointer}
    @media(prefers-color-scheme:dark){#${id} .panel,#${id} .alert{background:#0e1117;color:#f8fafc}#${id} .actions button{background:#111827;color:#f8fafc}#${id} .warn{color:#fbbf24}#${id} .err{color:#f87171}}
    @media(max-width:700px){#${id} .stats{grid-template-columns:repeat(2,1fr)}}
    </style>
    <button id="fab" class="fab ${state}" title="AutoTrader: ${esc(p.label||p.state)}">${String(p.state).toUpperCase()==='RED'?'!':'A'}</button>
    <div id="panel" class="panel"><h3>AutoTrader</h3><div class="summary">${esc(p.label)} · canonical V3 LIVE health</div>
      <div class="stats"><div class="stat"><b>${esc(p.live_count||0)}</b>LIVE</div><div class="stat"><b>${esc(pnl(p.open_pnl))}</b>Åpen P/L</div><div class="stat"><b>${esc(p.trades_24h||0)}</b>Handler 24t</div><div class="stat"><b>${esc(p.unresolved_orders||0)}</b>Uavklart</div></div>${rows||'<small>Ingen V3-instanser.</small>'}</div>
    <div id="back" class="back"><div class="alert"><h3>AutoTrader krever oppmerksomhet</h3><div>En LIVE-feil eller ubekreftet ordre er oppdaget.</div>${critical.map(x=>`<div class="msg">${esc(x)}</div>`).join('')}<div class="actions"><button id="close">Lukk</button><button id="open">Åpne status</button></div></div></div>`;
  const panel=root.querySelector('#panel'),back=root.querySelector('#back');
  root.querySelector('#fab')?.addEventListener('click',()=>panel?.classList.toggle('open'));
  root.querySelector('#close')?.addEventListener('click',()=>back?.classList.remove('open'));
  root.querySelector('#open')?.addEventListener('click',()=>{back?.classList.remove('open');panel?.classList.add('open')});
  const fp=String(p.alert_fingerprint||'');
  try{const prev=localStorage.getItem(store)||'';if(fp&&fp!==prev){back?.classList.add('open');localStorage.setItem(store,fp)}else if(!fp&&prev)localStorage.removeItem(store)}catch(_){if(fp)back?.classList.add('open')}
  parentElement.style.display='none';
  return()=>{};
}
"""

_component=st.components.v2.component(
    "pricegauger_autotrader_status_widget_v1",js=_WIDGET_JS,isolate_styles=False
)

@st.cache_data(ttl=10,show_spinner=False)
def _payload():
    s=load_autotrader_health_snapshot_v1(include_pnl=True)
    rows=[]
    for item in s.instances:
        row=asdict(item)
        if isinstance(item.runtime_updated_at,datetime):
            row["runtime_updated_at"]=item.runtime_updated_at.isoformat()
        rows.append(row)
    return {
        "state":s.state,"label":s.label,"live_count":s.live_count,"sim_count":s.sim_count,
        "unresolved_orders":s.unresolved_orders,"trades_24h":s.trades_24h,"open_pnl":s.open_pnl,
        "critical_messages":list(s.critical_messages),"alert_fingerprint":s.alert_fingerprint,"instances":rows,
    }

@st.fragment(run_every="10s")
def _fragment():
    try:
        payload=_payload()
    except Exception as exc:
        name=type(exc).__name__
        payload={"state":"RED","label":"Health-feil","live_count":0,"sim_count":0,"unresolved_orders":0,
                 "trades_24h":0,"open_pnl":None,"critical_messages":[f"AutoTrader health kunne ikke leses: {name}"],
                 "alert_fingerprint":f"health-read-{name}","instances":[]}
    _component(key="pricegauger-autotrader-global-health-v1",data={"payload":payload},height=0)

def render_autotrader_status_widget_v1()->None:
    """Mount global floating health status. Read-only; never sends execution requests."""
    _fragment()

__all__=["render_autotrader_status_widget_v1"]
