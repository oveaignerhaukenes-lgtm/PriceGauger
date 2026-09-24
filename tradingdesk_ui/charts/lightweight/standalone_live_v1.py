from __future__ import annotations

from typing import Any, Mapping
import streamlit as st

_LWC = "https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"

_JS = rf"""
const LIB_URL = {_LWC!r};

export default function(component) {{
  const {{ data, parentElement }} = component;
  const cfg = data.config || {{}};
  const market = String(cfg.market || "");
  const timeframe = String(cfg.timeframe || "5m");
  const windowHours = Number(cfg.window_hours || 12);
  const endpoint = String(cfg.endpoint || "/_stcore/live_chart_payload");
  const rootKey = market + "|" + timeframe;

  async function loadLib() {{
    if (window.LightweightCharts) return window.LightweightCharts;
    window.__pgLwcPromise ||= new Promise((resolve, reject) => {{
      const script = document.createElement("script");
      script.src = LIB_URL; script.async = true;
      script.onload = () => resolve(window.LightweightCharts);
      script.onerror = reject;
      document.head.appendChild(script);
    }});
    return window.__pgLwcPromise;
  }}

  const state = parentElement.__pgStandalone ||= {{ key: null, timer: null, chart: null, candles: null, status: null }};
  if (state.key !== rootKey) {{
    if (state.timer) clearInterval(state.timer);
    try {{ state.chart?.remove(); }} catch (_) {{}}
    parentElement.replaceChildren();
    const root = document.createElement("div");
    root.style.cssText = "height:720px;width:100%;position:relative";
    const status = document.createElement("div");
    status.style.cssText = "position:absolute;z-index:5;left:8px;top:8px;padding:4px 8px;border-radius:6px;background:#0e1117cc;color:#cbd5e1;font:12px system-ui";
    status.textContent = "kobler til Saxo-data…";
    root.appendChild(status); parentElement.appendChild(root);
    const LWC = await loadLib();
    const chart = LWC.createChart(root, {{ autoSize:true, layout:{{background:{{type:LWC.ColorType.Solid,color:"#0e1117"}},textColor:"#d5d9e0"}}, timeScale:{{timeVisible:true,secondsVisible:false}}, rightPriceScale:{{visible:true}} }});
    const candles = chart.addSeries(LWC.CandlestickSeries, {{upColor:"#16a34a",downColor:"#dc2626",borderUpColor:"#16a34a",borderDownColor:"#dc2626",wickUpColor:"#15803d",wickDownColor:"#b91c1c"}});
    Object.assign(state, {{key:rootKey, chart, candles, status}});
  }}

  async function tick() {{
    try {{
      const url = endpoint + "?market=" + encodeURIComponent(market) + "&timeframe=" + encodeURIComponent(timeframe) + "&window_hours=" + windowHours + "&_=" + Date.now();
      const response = await fetch(url, {{cache:"no-store"}});
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = await response.json();
      state.candles.setData(payload.candles || []);
      if (payload.forming_candle) state.candles.update(payload.forming_candle);
      state.status.textContent = "LIVE · " + (payload.forming_candle ? payload.forming_candle.close : "ingen forming") + " · " + new Date().toLocaleTimeString();
      if (!state.fitted && (payload.candles || []).length) {{ state.chart.timeScale().fitContent(); state.fitted = true; }}
    }} catch (error) {{
      state.status.textContent = "Live-feil: " + (error?.message || error);
    }}
  }}
  await tick();
  state.timer = setInterval(tick, 1000);
  return () => {{ if (state.timer) clearInterval(state.timer); state.timer = null; }};
}}
"""

_component = st.components.v2.component("pricegauger_standalone_live_chart_v1", js=_JS, isolate_styles=False)

def render_browser_live_chart_v1(config: Mapping[str, Any], *, key: str) -> None:
    _component(key=key, data={"config": dict(config)}, height=740)
