"""Reusable TradingView-style, fully interactive charts for Live-Sim Lab.

Shows genuine time-based data with mouse/touch pan, axis & wheel zoom, pinch,
crosshair, range presets, visibility toggles, and persistent per-chart viewport.
No broker imports and no order controls.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd
import streamlit as st


_TV_LAB_JS = r"""
export default function(component) {
  const { data, parentElement } = component;
  const payload = data.payload || {};
  const id = String(data.state_key || "lab-chart");
  const storageKey = "pricegauger:lab-tv:v2:" + id;
  let saved = { logical: null, height: 520 };
  try { saved = { ...saved, ...JSON.parse(localStorage.getItem(storageKey) || "{}") }; } catch (_) {}
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify(saved)); } catch (_) {} };
  const root = document.createElement("section");
  root.className = "lab-tv-wrap";
  Object.assign(root.style, { width:"100%", minWidth:"0", maxWidth:"100%", color:"inherit", fontFamily:"system-ui,-apple-system,sans-serif" });
  const heading = document.createElement("div");
  heading.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between;align-items:center;margin:0 0 6px";
  const name = document.createElement("strong"); name.textContent = String(payload.title || "Analyse");
  const controls = document.createElement("div");
  controls.style.cssText="display:flex;gap:4px;flex-wrap:wrap;align-items:center";
  heading.append(name, controls); root.appendChild(heading);
  const plot = document.createElement("div");
  plot.className = "lab-tv-plot";
  Object.assign(plot.style, {position:"relative",width:"100%",minWidth:"0",
    height: Math.max(290,Math.min(640,Number(saved.height)||520))+"px",
    touchAction:"pan-y",overflow:"hidden"});
  root.appendChild(plot);
  const legend = document.createElement("div");
  legend.style.cssText="display:flex;gap:8px 12px;flex-wrap:wrap;padding:6px 1px;font-size:12px;max-height:100px;overflow:auto";
  root.appendChild(legend);
  const foot = document.createElement("div");
  foot.style.cssText="font-size:11px;opacity:.72;margin-bottom:3px";
  foot.textContent="Dra: panorer · mus-hjul/knip: zoom · dra pris-/tidsakse: skalér · dobbeltklikk: tilpass · dra nederste kant: høyde";
  root.appendChild(foot);
  const handle = document.createElement("div");
  Object.assign(handle.style,{height:"13px",cursor:"ns-resize",touchAction:"none",display:"flex",justifyContent:"center",alignItems:"center",userSelect:"none"});
  const grip = document.createElement("div");
  Object.assign(grip.style,{width:"48px",height:"4px",background:"#94a3b8",opacity:".6",borderRadius:"9px"});
  handle.appendChild(grip);root.appendChild(handle);
  parentElement.replaceChildren(root);
  let chart = null;
  let disposed = false;
  let mounted = false;
  let loadingScript = null;
  const colors = ["#43a7f2","#26ac85","#e3a23f","#bd86ef","#f27480","#14b8a6","#6366f1","#ef9030","#dc6bb3"];
  const parseTime = x => Number(x);
  const allPoints = (payload.series || []).flatMap(x => x.points || []);
  const times = allPoints.map(p=>parseTime(p.time)).filter(Number.isFinite);
  if (payload.candles) times.push(...payload.candles.map(p=>parseTime(p.time)).filter(Number.isFinite));
  const earliest=Math.min(...times), latest=Math.max(...times);
  const addButton = (label,callback) => {
    const b=document.createElement("button");
    b.type="button"; b.textContent=label;
    Object.assign(b.style,{border:"1px solid #94a3b860",borderRadius:"6px",padding:"3px 7px",
      background:"transparent",color:"inherit",font:"600 11px system-ui",cursor:"pointer"});
    b.addEventListener("click",callback);controls.appendChild(b);return b;
  };
  const oslo=new Intl.DateTimeFormat("nb-NO",{timeZone:"Europe/Oslo",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
  function mount(L) {
    if (disposed || mounted) return;
    mounted=true;
    const dark=(()=>{try{return getComputedStyle(parentElement).color.match(/\d+/g).slice(0,3).map(Number).reduce((a,b)=>a+b,0)>430;}catch(_){return false;}})();
    const text=dark?"#d1d5db":"#344054";
    chart=L.createChart(plot,{
      autoSize:true,layout:{background:{type:"solid",color:"transparent"},textColor:text,fontSize:11},
      localization:{timeFormatter:t=>oslo.format(new Date(Number(t)*1000))},
      grid:{vertLines:{color:dark?"#ffffff11":"#94a3b822"},
            horzLines:{color:dark?"#ffffff11":"#94a3b822"}},
      timeScale:{timeVisible:true,secondsVisible:false,rightOffset:3,borderVisible:true,
        tickMarkFormatter:t=>oslo.format(new Date(Number(t)*1000))},
      rightPriceScale:{autoScale:true,borderVisible:true,scaleMargins:{top:0.09,bottom:0.10}},
      crosshair:{mode:L.CrosshairMode.Normal},
      handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
      handleScale:{axisPressedMouseMove:true,axisDoubleClickReset:true,mouseWheel:true,pinch:true},
      kineticScroll:{mouse:true,touch:true},
    });
    const options={priceLineVisible:false,lastValueVisible:true,crosshairMarkerVisible:true};
    const instruments=[];
    if (payload.candles?.length) {
      const candles=chart.addSeries(L.CandlestickSeries,{
        upColor:"#20b78c",downColor:"#dc6972",wickUpColor:"#20b78c",
        wickDownColor:"#dc6972",borderVisible:false,
        priceLineVisible:false,title:String(payload.price_title||"Markedspris"),
      });
      candles.setData(payload.candles);
      instruments.push({api:candles,name:String(payload.price_title||"Markedspris"),color:"#20b78c"});
      if (Array.isArray(payload.markers) && L.createSeriesMarkers) {
        const markers=payload.markers.map(m=>({
          time:m.time,position:m.value>0?"belowBar":"aboveBar",
          shape:m.value>0?"arrowUp":m.value<0?"arrowDown":"circle",
          color:m.value>0?"#21a67b":m.value<0?"#ea6c73":"#f0b74f",
          text:String(m.reason||"").slice(0,45),size:1
        })).sort((a,b)=>a.time-b.time);
        try { L.createSeriesMarkers(candles,markers); } catch (_) {}
      }
    }
    (payload.series||[]).forEach((series,i)=>{
      const color=colors[i%colors.length];
      const api=chart.addSeries(L.LineSeries,{
        ...options,color,lineWidth:i===0?3:2,title:String(series.name||"Strategi"),
        priceFormat:{type:"price",precision:series.precision??2,minMove:series.precision===0?1:.01},
      });
      api.setData(series.points||[]);
      instruments.push({api,name:String(series.name||"Strategi"),color});
    });
    for(const item of instruments){
      const toggle=document.createElement("button");
      toggle.type="button"; toggle.title="Vis/skjul "+item.name;
      Object.assign(toggle.style,{border:"0",background:"transparent",color:"inherit",
        cursor:"pointer",display:"flex",alignItems:"center",gap:"5px",padding:"3px"});
      const dot=document.createElement("span");
      Object.assign(dot.style,{width:"9px",height:"9px",borderRadius:"3px",background:item.color});
      const label=document.createElement("span");label.textContent=item.name;
      toggle.append(dot,label);legend.appendChild(toggle);
      let visible=true;
      toggle.addEventListener("click",()=>{
        visible=!visible;item.api.applyOptions({visible});
        toggle.style.opacity=visible?"1":".4";
      });
    }
    const durations=[["1t",3600],["4t",14400],["1d",86400],["3d",259200],["7d",604800]];
    durations.forEach(([label,seconds])=>addButton(label,()=>{
      if(!Number.isFinite(latest))return;
      chart.timeScale().setVisibleRange({from:Math.max(earliest,latest-seconds),to:latest+60});
    }));
    addButton("Alt",()=>chart.timeScale().fitContent());
    addButton("−",()=>chart.timeScale().applyOptions({barSpacing:Math.max(1,chart.timeScale().options().barSpacing*.75)}));
    addButton("+",()=>chart.timeScale().applyOptions({barSpacing:Math.min(100,chart.timeScale().options().barSpacing*1.33)}));
    addButton("↺",()=>{saved.logical=null;persist();chart.timeScale().fitContent();});
    if(saved.logical && Number.isFinite(saved.logical.from) && Number.isFinite(saved.logical.to)) {
      try { chart.timeScale().setVisibleLogicalRange(saved.logical); } catch(_){chart.timeScale().fitContent();}
    } else if(times.length) {
      // Avoid squeezing an entire multi-week run into 400 pixels initially.
      const first=times.length>1200?latest-86400*3:earliest;
      try {chart.timeScale().setVisibleRange({from:Math.max(earliest,first),to:latest+60});}
      catch (_){chart.timeScale().fitContent();}
    }
    let saveQueued=false;
    chart.timeScale().subscribeVisibleLogicalRangeChange(range=>{
      if(disposed||!range||saveQueued)return;
      saveQueued=true;
      requestAnimationFrame(()=>{saveQueued=false;
        if(!disposed){saved.logical=chart.timeScale().getVisibleLogicalRange();persist();}
      });
    });
    plot.addEventListener("dblclick",()=>{saved.logical=null;chart.timeScale().fitContent();persist();});
  }
  let resizeActive=false, startY=0, startHeight=0;
  handle.addEventListener("pointerdown",event=>{
    event.preventDefault();resizeActive=true;startY=event.clientY;
    startHeight=plot.getBoundingClientRect().height;
    handle.setPointerCapture?.(event.pointerId);
  });
  handle.addEventListener("pointermove",event=>{
    if(!resizeActive)return;
    saved.height=Math.round(Math.max(290,Math.min(640,startHeight+event.clientY-startY)));
    plot.style.height=saved.height+"px";
  });
  for(const type of ["pointerup","pointercancel"])handle.addEventListener(type,()=>{
    if(resizeActive){resizeActive=false;persist();}
  });
  const load=()=>{
    if(window.LightweightCharts){mount(window.LightweightCharts);return;}
    loadingScript=document.createElement("script");
    loadingScript.src="https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js";
    loadingScript.onload=()=>mount(window.LightweightCharts);
    loadingScript.onerror=()=>{plot.textContent="Kan ikke laste TradingView-grafen. Tabellen er fortsatt tilgjengelig.";};
    document.head.appendChild(loadingScript);
  };
  load();
  return ()=>{disposed=true;try{chart?.remove();}catch(_){}
    try{loadingScript?.remove();}catch(_){}try{root.remove();}catch(_){}
  };
}
"""

_lab_tv_component=st.components.v2.component(
    "pricegauger_live_sim_tv_v2",js=_TV_LAB_JS,isolate_styles=False)


def _stamp(value) -> int:
    """Timestamp interpreted in UTC; do not shift candles for Oslo labels."""
    ts=pd.Timestamp(value)
    if ts.tzinfo is None:
        ts=ts.tz_localize("UTC")
    else:
        ts=ts.tz_convert("UTC")
    return int(ts.timestamp())


def build_tv_series_payload(frame: pd.DataFrame, *, title: str) -> dict:
    """Convert pivot dataframe to monotonic UNIX seconds and finite values."""
    if frame.empty:
        return {"title":title,"series":[]}
    series=[]
    for column in frame.columns:
        points=[]
        for stamp,value in frame[column].items():
            if pd.isna(value) or not isfinite(float(value)):
                continue
            points.append({"time":_stamp(stamp),"value":round(float(value),8)})
        unique={point["time"]:point for point in points}
        points=[unique[t] for t in sorted(unique)]
        if points:
            series.append({"name":str(column),"points":points,
                           "precision":0 if all(float(x["value"]).is_integer() for x in points) else 2})
    return {"title":title,"series":series}


def build_tv_candle_payload(bars, fills=(), *, title="Pris og PAPER-handler") -> dict:
    candles={}
    for bar in bars:
        stamp=_stamp(bar.bar_time)
        values=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
        if all(isfinite(v) and v>0 for v in values):
            candles[stamp]={"time":stamp,"open":values[0],"high":values[1],
                            "low":values[2],"close":values[3]}
    markers=[]
    for at,amount,reason,tf,price in fills:
        stamp=_stamp(at)
        if stamp in candles:
            markers.append({"time":stamp,"value":float(amount),
                            "reason":f"{reason} · {amount:+g} @ {tf}m"})
    return {"title":title,"price_title":"Markedspris",
            "candles":[candles[t] for t in sorted(candles)],
            "markers":sorted(markers,key=lambda x:x["time"]),
            "series":[]}


def render_lab_tv_series(frame: pd.DataFrame, *, key: str,
                         title: str="Netto PAPER-avkastning (%)") -> None:
    payload=build_tv_series_payload(frame,title=title)
    if not payload["series"]:
        st.caption("Ingen datapunkter å vise i grafen.")
        return
    _lab_tv_component(key="lab-tv:"+key, data={"payload":payload,"state_key":key},
                      height=760)


def render_lab_tv_candles(bars, fills=(), *, key: str,
                          title: str="Markedspris og PAPER-handler") -> None:
    payload=build_tv_candle_payload(bars,fills,title=title)
    if not payload["candles"]:
        st.caption("Ingen ferdige candles å vise.")
        return
    _lab_tv_component(key="lab-tv:"+key,data={"payload":payload,"state_key":key},
                      height=970)


__all__=["render_lab_tv_series","render_lab_tv_candles",
         "build_tv_series_payload","build_tv_candle_payload","_TV_LAB_JS"]
