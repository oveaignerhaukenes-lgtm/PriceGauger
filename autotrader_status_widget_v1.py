from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import streamlit as st

from autotrader_health_v1 import load_autotrader_health_snapshot_v1


_WIDGET_JS = r"""
export default function(component) {
  const {data,parentElement,setTriggerValue}=component, p=data.payload||{};
  const id='pg-at-health-v1', store='pg-at-alert-v1';
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const pnl=v=>Number.isFinite(Number(v))?`${Number(v)>=0?'+':''}${Number(v).toFixed(2)}`:'—';
  const age=v=>Number(v)<60?`${Math.round(Number(v))} s`:`${(Number(v)/60).toFixed(1)} min`;
  const when=v=>{try{return v?new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(v)):'—'}catch(_){return String(v||'—')}};
  let root=document.getElementById(id);
  if(!root){root=document.createElement('div');root.id=id;document.body.appendChild(root)}
  const wasPanelOpen=!!root.querySelector('#panel.open');
  const state=String(p.state||'IDLE').toLowerCase();
  // A recent SUBMITTED state is a normal order in transit, not a reset failure.
  const orderStatus=x=>{
    const status=String(x.pending_state||'').toUpperCase();
    if(!status)return '';
    const seconds=Number(x.pending_age_seconds);
    const elapsed=Number.isFinite(seconds)?seconds:0;
    const brokerId=x.broker_order_id?` · Saxo ${esc(x.broker_order_id)}`:'';
    const name=`Ordre ${esc(status)} · ${esc(age(elapsed))}${brokerId}`;
    if(status==='SUBMITTED' && elapsed<15)
      return `<small class="neutral">${name} · Avstemmer med Saxo (normalt)</small>`;
    if(status==='SUBMITTED' && x.broker_working===true)
      return `<small class="neutral">${name} · Ordren er aktiv hos Saxo</small>`;
    if(status==='SUBMITTING' && elapsed<15)
      return `<small class="neutral">${name} · Sender til Saxo</small>`;
    if(status==='RESERVED' && elapsed<15)
      return `<small class="neutral">${name} · Forbereder ordre</small>`;
    return `<small class="warn">${name} · Avventer ordreavstemming</small>`;
  };
  const rows=Array.from(p.instances||[]).map(x=>`
    <div class="row">
      <div><span class="dot ${String(x.severity||'IDLE').toLowerCase()}"></span><b>${esc(x.account_name||x.account_id)}</b><span class="right">${x.live_armed?'LIVE':(x.sim_armed?'SIM':'AV')}</span></div>
      <small>${esc(x.market_name)} · ${esc(x.runtime_status)} · P/L ${esc(pnl(x.open_pnl))}</small>
      <small><b>Strategi:</b> ${esc(x.strategy_label||x.strategy_key||'—')}</small>
      <small>Sist ${esc(when(x.runtime_updated_at))} · Handler 24t ${esc(x.trades_24h)}</small>
      <small>Marked ${esc(x.market_state||(x.market_open===true?'Open':(x.market_open===false?'Closed':'ukjent')))}</small>
      ${orderStatus(x)}
      ${x.issue_message?`<small class="err">${esc(x.issue_message)}</small>`:''}
      ${x.pending_state==='RESERVED' && Number(x.pending_age_seconds)>=120 && !x.broker_order_id
        ?`<button type="button" class="recover" data-id="${esc(x.instance_id)}" data-key="${esc(x.pending_request_key)}" data-account="${esc(x.account_name)}">Reset ordre</button>`:''}
    </div>`).join('');
  const ai=p.ai_trader||{};
  const aiSeverity=String(ai.severity||'IDLE').toLowerCase();
  const aiRow=`
    <div class="row" aria-label="AI Trader status">
      <div><span class="dot ${esc(aiSeverity)}"></span><b>AI Trader · PAPER</b>
        <span class="right">${esc(ai.label||'Ikke startet')}</span></div>
      <small>${esc(ai.detail||'Ingen forskningsstatus')}</small>
      <small>Worker ${esc(when(ai.last_tick))} · Siste quote ${esc(when(ai.last_quote))}</small>
      <small>Modell ${esc(ai.last_model_status||'Ingen vurderinger')}
        · Siste beslutning ${esc(when(ai.last_decision))}</small>
    </div>`;
  const critical=Array.from(p.critical_messages||[]);
  const active=Array.from(p.instances||[]).filter(x=>x.live_armed);
  const palette={GREEN:'#22c55e',YELLOW:'#f59e0b',RED:'#ef4444',IDLE:'#64748b'};
  const counts={GREEN:0,YELLOW:0,RED:0,IDLE:0};
  active.forEach(x=>{const key=String(x.severity||'IDLE').toUpperCase();counts[key in counts?key:'IDLE']+=1});
  let cursor=0;
  const sectors=[];
  ['GREEN','YELLOW','RED','IDLE'].forEach(key=>{
    if(!counts[key]||!active.length)return;
    const next=cursor+(counts[key]/active.length)*100;
    sectors.push(`${palette[key]} ${cursor}% ${next}%`);
    cursor=next;
  });
  const healthGradient=active.length?`conic-gradient(${sectors.join(',')})`:'#64748b';
  root.innerHTML=`
    <style>
    #${id}{font-family:system-ui,sans-serif}#${id} button{font:inherit}
    #${id} .fab{position:fixed;right:14px;bottom:14px;z-index:1000001;width:48px;height:48px;border-radius:50%;border:3px solid white;color:white;font-weight:800;font-size:20px;box-shadow:0 4px 18px #0005;cursor:pointer}
    #${id} .green{background:#22c55e}#${id} .yellow{background:#f59e0b}#${id} .red{background:#ef4444}#${id} .idle{background:#64748b}
    #${id} .panel{position:fixed;right:14px;bottom:72px;z-index:1000000;width:min(420px,calc(100vw - 28px));max-height:70vh;overflow:auto;display:none;background:#fff;color:#111827;border:1px solid #94a3b866;border-radius:14px;padding:12px;box-shadow:0 14px 40px #0005}
    #${id} .panel.open{display:block}#${id} h3{margin:0 0 4px}#${id} .summary{font-size:12px;margin-bottom:8px;opacity:.72}
    #${id} .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}#${id} .stat{text-align:center;border:1px solid #94a3b844;border-radius:8px;padding:6px;font-size:10px}#${id} .stat b{display:block;font-size:14px}
    #${id} .row{border:1px solid #94a3b844;border-radius:9px;padding:8px;margin-top:7px;font-size:12px}#${id} small{display:block;margin-top:3px;overflow-wrap:anywhere}#${id} .right{float:right}#${id} .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
    #${id} .neutral{opacity:.73}
    #${id} .recover{display:block;margin-top:7px;border:1px solid #64748b;background:transparent;color:inherit;padding:7px 10px;border-radius:8px;cursor:pointer}
    #${id} .recover:hover{background:#64748b22}
    #${id} .back{position:fixed;inset:0;z-index:1000003;display:none;background:#0f172a66;align-items:center;justify-content:center;padding:16px}#${id} .back.open{display:flex}
    #${id} .alert{width:min(500px,calc(100vw - 28px));background:#fff;color:#111827;border:2px solid #ef4444;border-radius:14px;padding:16px;box-shadow:0 18px 55px #0006}#${id} .msg{margin:8px 0;padding:7px;border-left:4px solid #ef4444;background:#ef444411}
    #${id} .actions{text-align:right;margin-top:12px}#${id} .actions button{margin-left:6px;padding:7px 10px;border-radius:8px;border:1px solid #94a3b8;background:#fff;cursor:pointer}
    @media(prefers-color-scheme:dark){#${id} .panel,#${id} .alert{background:#0e1117;color:#f8fafc}#${id} .actions button{background:#111827;color:#f8fafc}#${id} .warn{color:#fbbf24}#${id} .err{color:#f87171}}
    @media(max-width:700px){#${id} .stats{grid-template-columns:repeat(2,1fr)}}
    </style>
    <button id="fab" class="fab ${state}" style="background:${healthGradient}" title="AutoTrader: ${esc(p.label||p.state)}">${String(p.state).toUpperCase()==='RED'?'!':'A'}</button>
    <div id="panel" class="panel"><h3>AutoTrader</h3><div class="summary">${esc(p.label)} · canonical V3 LIVE health</div>
      <div class="stats"><div class="stat"><b>${esc(p.live_count||0)}</b>LIVE</div><div class="stat"><b>${esc(pnl(p.open_pnl))}</b>Åpen P/L</div><div class="stat"><b>${esc(p.trades_24h||0)}</b>Handler 24t</div><div class="stat"><b>${esc(p.unresolved_orders||0)}</b>Uavklart</div></div>${aiRow}${rows||'<small>Ingen V3-instanser.</small>'}</div>
    <div id="back" class="back"><div class="alert"><h3>AutoTrader krever oppmerksomhet</h3><div>En LIVE-feil eller ubekreftet ordre er oppdaget.</div>${critical.map(x=>`<div class="msg">${esc(x)}</div>`).join('')}<div class="actions"><button id="close">Lukk</button><button id="open">Åpne status</button></div></div></div>`;
  const panel=root.querySelector('#panel'),back=root.querySelector('#back');
  if(wasPanelOpen)panel?.classList.add('open');
  root.querySelector('#fab')?.addEventListener('click',()=>panel?.classList.toggle('open'));
  root.querySelectorAll('button.recover').forEach(button=>button.addEventListener('click',()=>{
    if(button.disabled)return;
    button.disabled=true;
    button.textContent='Kontrollerer Saxo …';
    setTriggerValue('recovery_request',JSON.stringify({
      instance_id:button.dataset.id,
      request_key:button.dataset.key,
      nonce:String(Date.now())
    }));
  }));
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
    # Research AI is observational. Its health MUST NOT affect LIVE severity,
    # alert fingerprint, unresolved-order counts, or green/yellow/red fleet pin.
    try:
        from live_sim_ai_technical_status_v1 import load_ai_technical_status
        ai=load_ai_technical_status()
    except Exception as exc:
        ai={"code":"UNAVAILABLE","label":"Kan ikke leses","severity":"YELLOW",
            "detail":"Statusdatabase utilgjengelig: "+type(exc).__name__,
            "last_tick":None,"last_quote":None,"last_decision":None,
            "last_model_status":None}
    return {
        "ai_trader":ai,
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
                 "alert_fingerprint":f"health-read-{name}","instances":[],
                 "ai_trader":{"code":"UNAVAILABLE","label":"Kan ikke leses",
                              "severity":"YELLOW","detail":"Status kunne ikke lastes"}}
    response=_component(key="pricegauger-autotrader-global-health-v1",data={"payload":payload},
                        height=0,on_recovery_request_change=lambda: None)
    raw=getattr(response,"recovery_request",None)
    if not raw:
        return
    try:
        event=json.loads(str(raw))
        nonce=str(event["nonce"])
        if st.session_state.get("v3_last_recovery_nonce")==nonce:
            return
        st.session_state["v3_last_recovery_nonce"]=nonce
        from autotrader_v3_operator_order_recovery_v1 import recover_stale_reserved_v3
        detail=recover_stale_reserved_v3(
            instance_id=str(event["instance_id"]),
            request_key=str(event["request_key"]),
        )
    except Exception as exc:
        st.toast("Ordrelåsen ble IKKE resatt: "+str(exc),icon="⚠️")
    else:
        _payload.clear()
        st.toast("Ordreavstemming: "+detail,icon="✅")
        st.rerun(scope="fragment")

def render_autotrader_status_widget_v1()->None:
    """Mount global V3 status and broker-verified nontrading recovery control."""
    _fragment()

__all__=["render_autotrader_status_widget_v1"]
