"""New independent MACD family PAPER workspace. Legacy experiments stay untouched."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from live_sim_lab_store_v1 import lab_snapshot
from macd_nextgen_paper_v1 import MacdConfig, replay, SUPPORTED_MINUTES, ENGINE_VERSION


@st.cache_data(ttl=60, show_spinner=False)
def _recent_bars(instrument_id: int, start_iso: str, end_iso: str):
    return CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id),
        start=start_iso, end=end_iso, limit=40000,
    )


_CHART_TEMPLATE = r"""
<style>
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,sans-serif;color:var(--chart-fg,#d3d8e0);background:transparent}
#ng-shell{display:grid;grid-template-columns:minmax(0,1fr) 245px;gap:12px;min-height:445px}
#ng-plot{min-width:0;height:442px;position:relative}
#ng-legend{height:440px;overflow:auto;border-left:1px solid rgba(155,164,175,.25);padding:0 0 0 10px}
.ng-entry{width:100%;text-align:left;border:0;background:transparent;color:inherit;padding:10px 7px;border-radius:8px;cursor:pointer;display:flex;gap:7px;align-items:flex-start}
.ng-entry:hover,.ng-entry:focus-visible{background:rgba(125,140,155,.16)}
.ng-rank{min-width:18px;opacity:.65}
.ng-swatch{min-width:9px;height:9px;border-radius:50%;margin-top:5px}
.ng-label{font-size:12px;line-height:1.35}
.ng-return{font-size:12px;white-space:nowrap;margin-left:auto;font-variant-numeric:tabular-nums;font-weight:600}
#ng-hint{font-size:11px;opacity:.65;padding:8px}
#ng-hover{position:absolute;pointer-events:none;font-size:12px;padding:5px 8px;border-radius:6px;background:rgba(20,26,35,.92);color:#fff;z-index:12;display:none;max-width:300px;box-shadow:0 2px 10px #0004}
@media(max-width:720px){#ng-shell{display:block}#ng-plot{height:350px}#ng-legend{height:auto;max-height:220px;overflow:auto;border-left:0;border-top:1px solid #7775;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px}.ng-entry{padding:6px;font-size:11px}.ng-return{font-size:11px}}
</style>
<div id="ng-shell"><div id="ng-plot"><div id="ng-hover"></div></div><div id="ng-legend" aria-label="Strategier sortert etter avkastning"><div id="ng-hint">Klikk navn for å isolere. Dobbeltklikk en kurve for å isolere den. Gjenta for å vise alle.</div></div></div>
<script src="https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
(() => {
  const rows = __PAYLOAD__;
  const host = document.getElementById('ng-plot');
  const legend = document.getElementById('ng-legend');
  const hint = document.getElementById('ng-hint');
  const tooltip = document.getElementById('ng-hover');
  if(!window.LightweightCharts){host.textContent='Grafbiblioteket er utilgjengelig. Resultatene vises i tabellen over.';return;}
  const LWC=window.LightweightCharts;
  const chart=LWC.createChart(host,{
    autoSize:true,
    layout:{background:{type:'solid',color:'transparent'},textColor:'#9097a3',fontSize:11},
    grid:{vertLines:{color:'rgba(135,145,160,.10)'},horzLines:{color:'rgba(135,145,160,.10)'}},
    rightPriceScale:{borderVisible:false},
    timeScale:{timeVisible:true,secondsVisible:false,borderVisible:false,rightOffset:1},
    crosshair:{mode:LWC.CrosshairMode.Normal},
    handleScale:{axisDoubleClickReset:false},
    localization:{priceFormatter:v=>v.toFixed(2)+' %'}
  });
  const colors=['#36b58b','#f4a340','#50a4ef','#cc75ea','#e96e6e','#a1a6b0'];
  let isolated=null, hovered=null;
  const entries=rows.map((row,i)=>{
    const color=colors[i%colors.length];
    const api=chart.addSeries(LWC.LineSeries,{color,lineWidth:i===0?3:2,
      lastValueVisible:false,priceLineVisible:false,
      crosshairMarkerVisible:true});
    api.setData(row.points.map(p=>({time:Math.round(Date.parse(p[0])/1000),value:p[1]})));
    const btn=document.createElement('button');
    btn.type='button';btn.className='ng-entry';btn.title='Vis bare '+row.name;
    const rank=document.createElement('span');rank.className='ng-rank';rank.textContent=(i+1)+'.';
    const swatch=document.createElement('span');swatch.className='ng-swatch';swatch.style.background=color;
    const label=document.createElement('span');label.className='ng-label';label.textContent=row.name;
    const profit=document.createElement('span');profit.className='ng-return';profit.textContent=(row.value>=0?'+':'')+row.value.toFixed(2)+'%';
    btn.append(rank,swatch,label,profit);legend.append(btn);
    btn.addEventListener('click',()=>toggle(row.id));
    return {api,row,btn,color};
  });
  function toggle(id){
    isolated=(isolated===id?null:id);
    entries.forEach(e=>{
      const visible=isolated===null||e.row.id===isolated;
      e.api.applyOptions({visible});
      e.btn.style.opacity=visible?'1':'.4';
      e.btn.setAttribute('aria-pressed',isolated===e.row.id?'true':'false');
    });
  }
  chart.subscribeCrosshairMove(p=>{
    hovered=null;
    if(!p||!p.point||!p.time){tooltip.style.display='none';return;}
    let distance=Number.POSITIVE_INFINITY;
    for(const e of entries){
      if(isolated&&isolated!==e.row.id)continue;
      const datum=p.seriesData.get(e.api);
      const val=datum?.value??datum?.close;
      if(!Number.isFinite(val))continue;
      const y=e.api.priceToCoordinate(val);
      if(y===null)continue;
      const d=Math.abs(y-p.point.y);
      if(d<distance){distance=d;hovered=e;}
    }
    if(!hovered||distance>17){tooltip.style.display='none';hovered=null;return;}
    tooltip.textContent=hovered.row.name;
    tooltip.style.left=Math.max(4,Math.min(host.clientWidth-230,p.point.x+13))+'px';
    tooltip.style.top=Math.max(3,p.point.y-32)+'px';
    tooltip.style.display='block';
  });
  host.addEventListener('dblclick',event=>{
    if(hovered){event.preventDefault();event.stopImmediatePropagation();toggle(hovered.row.id);}
  },true);
  if(!rows.length){hint.textContent='Ingen signaler i valgt periode.';}
  chart.timeScale().fitContent();
})();
</script>
"""


def _plot_reports(reports):
    payload = [{"id":r.identity,"name":r.label,"value":r.return_pct,
                "points":[[t,round(pct,6)] for t,pct,_ in r.points]}
               for r in reports]
    body = _CHART_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    components.html(body, height=535, scrolling=False)


@st.fragment(run_every="60s")
def render_nextgen_macd_lab_v1():
    st.subheader("Nye strategier · MACD")
    st.caption("NextGen v1 · isolert PAPER-replay på faktiske ferdige 1m-markedsbarer. "
               "Ingen LIVE-ordre. Endring av brytere beregner alle valgte signalperioder på nytt.")
    try:
        _existing, _memory, feeds = lab_snapshot()
    except Exception as exc:
        st.warning("Markedsfeed kan ikke leses fra Live-Sim Lab: "+type(exc).__name__)
        return
    if not feeds:
        st.info("Venter på markedsdata fra Live-Sim Lab.")
        return

    feed_options={str(x["instrument_id"]):x for x in feeds}
    source=st.selectbox("Marked",list(feed_options),format_func=lambda k:feed_options[k]["market_name"],
                        key="nextgen:source")
    feed=feed_options[source]
    periods=st.multiselect("Perioder som skal sammenlignes (minutter)",SUPPORTED_MINUTES,
                           default=(2,5,10),key="nextgen:periods")
    c1,c2,c3,c4=st.columns(4)
    flip=c1.toggle("Flip",value=True,key="nextgen:flip",
                   help="Nytt kryss reverserer vanlig posisjon, men pyramide går først FLAT.")
    hold=c2.toggle("Hold before flip",value=True,key="nextgen:hold",
                   help="Ikke trapp ned når histogramimpulsen svekkes innen samme MACD-regime.")
    pyramid=c3.toggle("Pyramide",value=False,key="nextgen:pyramid",
                      help="Bygg én tranche ved positiv impuls. Motsatt regime lukker ALT til FLAT.")
    trail=c4.toggle("Trailing",value=False,key="nextgen:trail",disabled=hold,
                    help="Bare uten Hold: trapp ned i samme regime ved svekket impuls.")
    effective_trail=trail and not hold
    if hold and trail:
        st.caption("Trailing er inaktiv når Hold before flip er på.")
    cfg_help=("Pyramide + motsatt MACD-signal → FLAT, deretter gjenoppbygging fra minste "
              "tranche først etter neste ferdige signallys.")
    st.caption(cfg_help)
    c5,c6,c7,c8=st.columns([1.0,1.1,1.3,1.0])
    days=c5.selectbox("Analyseperiode (dager)",(1,3,7,14),index=1,key="nextgen:days")
    tranches=c6.number_input("Maks trancher",min_value=1,max_value=20,value=5,
                             step=1,disabled=not (pyramid or effective_trail),key="nextgen:tranches")
    charge=c7.toggle("Inkluder kostnader",value=True,key="nextgen:costs")
    c8.caption("0,08 % er en foreløpig brukerantakelse, ikke bekreftet Saxo-sats.")
    cp1,cp2=st.columns(2)
    fee_pct=cp1.number_input("Avgift per side (%)",min_value=0.0,max_value=2.0,
                             value=0.08,step=0.01,format="%.3f",key="nextgen:fee",disabled=not charge)
    spread_pct=cp2.number_input("Full kjøp/salg-spread (%)",min_value=0.0,max_value=1.0,
                                value=0.01,step=0.005,format="%.3f",key="nextgen:spread",disabled=not charge)
    st.caption("Ved reversering beregnes **to sider**: lukking + åpning. "
               "SIM fyller til neste 1m-åpning; faktisk slippage, finansiering og Saxo-fill "
               "er ikke modellert. Dette er historisk PAPER-replay, ikke LIVE-resultat eller uavhengig forwardtest.")
    if not periods:
        st.info("Velg minst én signalperiode.")
        return
    try:
        anchor=min(datetime.now(timezone.utc),datetime.fromisoformat(
            str(feed["last_bar_time"]).replace("Z","+00:00"))+timedelta(minutes=1))
        since=anchor-timedelta(days=int(days))
        bars=_recent_bars(int(source),(since-timedelta(days=7)).isoformat(),anchor.isoformat())
        if not bars:
            st.info("Ingen kanoniske markedsbarer i valgt tidsrom.")
            return
        reports=[replay(MacdConfig(minutes=int(tf),flip=flip,hold_before_flip=hold,
                                   pyramide=pyramid,trailing=effective_trail,
                                   max_tranches=int(tranches)),bars,started_at=since,
                        costs_enabled=charge,commission_side_bps=fee_pct*100,
                        quoted_spread_bps=spread_pct*100)
                 for tf in periods]
    except Exception as exc:
        st.error("NextGen SIM kunne ikke beregnes: "+type(exc).__name__)
        return
    reports.sort(key=lambda result:(-result.return_pct,result.identity))
    st.caption("Delt datavindu: "+since.strftime("%d.%m %H:%M")+"–"+
               anchor.strftime("%d.%m %H:%M")+" UTC · motor "+ENGINE_VERSION)
    table=pd.DataFrame([{
        "Strategi":p.label,
        "Netto SIM %":round(p.return_pct,3),
        "Brutto %":round(p.gross_pct,3),
        "Maks DD %":round(p.max_drawdown_pct,3),
        "SIM-endringer":p.executions,
        "Est. Saxo-ordrer":p.estimated_broker_orders,
        "Est. kostnad % av start":round(p.total_cost_pct,3),
        "Signalbarer":p.completed_signal_bars,
    } for p in reports])
    st.dataframe(table,hide_index=True,use_container_width=True)
    st.caption("Legenden nedenfor sorteres etter avkastning i valgt periode. "
               "Dobbeltklikk en kurve eller klikk legend-navn for å isolere; gjenta for alle.")
    _plot_reports(reports)

    # Completely isolated AEn PAPER workspace; no changes to NextGen execution.
    with st.expander("AEn Core · Adaptive Engine (SIM)", expanded=True):
        from aen_lab_ui_v1 import render_aen_core_lab_v1
        render_aen_core_lab_v1()
