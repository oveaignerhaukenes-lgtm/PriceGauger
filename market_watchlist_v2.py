from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import streamlit as st

from instrument_registry_v2 import list_subscribed_sources_v2
from realtime_market_data import RealtimeMarketDataStore


_WATCHLIST_KEY = "pg-watchlist-markets-v2"


def _safe_markets() -> tuple[str, ...]:
    try:
        return tuple(sorted({item.market_name for item in list_subscribed_sources_v2(provider="saxo")}))
    except Exception:
        return ()


def _series_for_market(store: RealtimeMarketDataStore, market: str) -> dict:
    now = datetime.now(timezone.utc)
    try:
        bars = tuple(store.load_range(market=market, start=now - timedelta(hours=4), end=now, limit=300))
    except Exception:
        bars = ()
    if not bars:
        return {"market": market, "price": None, "change_pct": None, "points": []}
    closes = [float(item.close) for item in bars if item.close is not None]
    if not closes:
        return {"market": market, "price": None, "change_pct": None, "points": []}
    first = closes[0]
    last = closes[-1]
    change_pct = None if first == 0 else ((last / first) - 1.0) * 100.0
    return {
        "market": market,
        "price": last,
        "change_pct": change_pct,
        "points": closes[-80:],
    }


def _render_component(rows: Iterable[dict]) -> None:
    payload = {"rows": list(rows)}
    js = r"""
export default function(component) {
  const {data, parentElement} = component;
  const rows = Array.from(data.rows || []);
  const storageKey = 'pricegauger:watchlist-drawer:v2';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) {}
  let width = Math.max(44, Math.min(420, Number(saved.width || 46)));

  parentElement.replaceChildren();
  parentElement.style.height = '0px';
  parentElement.style.overflow = 'visible';

  const drawer = document.createElement('aside');
  Object.assign(drawer.style, {
    position: 'fixed', right: '0', top: '5.2rem', bottom: '1rem', width: `${width}px`, zIndex: '9999',
    background: 'rgba(15,23,42,.96)', color: '#f8fafc', border: '1px solid rgba(148,163,184,.28)',
    borderRight: '0', borderRadius: '12px 0 0 12px', boxShadow: '0 14px 36px rgba(15,23,42,.25)',
    overflow: 'hidden', transition: 'box-shadow 120ms ease', font: '500 12px/1.25 system-ui,-apple-system,sans-serif'
  });
  parentElement.appendChild(drawer);

  const handle = document.createElement('div');
  Object.assign(handle.style, {
    position:'absolute', left:'0', top:'0', bottom:'0', width:'9px', cursor:'ew-resize',
    background:'linear-gradient(90deg,rgba(56,189,248,.55),rgba(56,189,248,0))', zIndex:'3'
  });
  drawer.appendChild(handle);

  const header = document.createElement('div');
  Object.assign(header.style, {height:'42px', display:'flex', alignItems:'center', gap:'8px', padding:'0 10px 0 14px', borderBottom:'1px solid rgba(148,163,184,.18)'});
  header.innerHTML = '<strong style="font-size:12px;white-space:nowrap">Watchlist</strong><span style="opacity:.58;font-size:10px;white-space:nowrap">dra kanten</span>';
  drawer.appendChild(header);

  const body = document.createElement('div');
  Object.assign(body.style, {height:'calc(100% - 42px)', overflowY:'auto', padding:'4px 6px 10px 10px'});
  drawer.appendChild(body);

  const fmt = (v) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('nb-NO',{maximumFractionDigits:Math.abs(Number(v))>=100?2:3}) : '—';
  function spark(values, positive) {
    const vals = Array.from(values || []).map(Number).filter(Number.isFinite);
    if (vals.length < 2) return '';
    const min = Math.min(...vals), max = Math.max(...vals), span = Math.max(1e-9,max-min);
    const pts = vals.map((v,i)=>`${(i/(vals.length-1))*88},${25-((v-min)/span)*22}`).join(' ');
    const stroke = positive ? '#4ade80' : '#f87171';
    return `<svg width="90" height="28" viewBox="0 0 90 28" preserveAspectRatio="none" aria-hidden="true"><polyline fill="none" stroke="${stroke}" stroke-width="1.6" points="${pts}"/></svg>`;
  }

  rows.forEach((row) => {
    const item = document.createElement('div');
    Object.assign(item.style, {minHeight:'45px', display:'grid', gridTemplateColumns:'minmax(0,1fr) auto', alignItems:'center', gap:'8px', padding:'5px 4px', borderBottom:'1px solid rgba(148,163,184,.10)'});
    const change = Number(row.change_pct);
    const positive = Number.isFinite(change) && change >= 0;
    const delta = Number.isFinite(change) ? `${change>=0?'+':''}${change.toFixed(2)}%` : '—';
    const left = document.createElement('div');
    left.innerHTML = `<div style="font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${row.market || ''}</div><div style="display:flex;gap:6px;align-items:center"><span style="font-size:11px">${fmt(row.price)}</span><span style="font-size:10px;color:${positive?'#4ade80':'#f87171'}">${delta}</span></div>`;
    item.appendChild(left);
    const graph = document.createElement('div');
    graph.className = 'pg-watchlist-spark';
    graph.innerHTML = spark(row.points, positive);
    item.appendChild(graph);
    body.appendChild(item);
  });

  function applyWidth(next) {
    width = Math.max(44, Math.min(420, next));
    drawer.style.width = `${width}px`;
    header.style.opacity = width < 105 ? '0' : '1';
    body.querySelectorAll('.pg-watchlist-spark').forEach((el)=>{ el.style.display = width >= 245 ? 'block' : 'none'; });
    body.querySelectorAll('div').forEach(()=>{});
  }
  applyWidth(width);

  let dragging = false;
  handle.addEventListener('pointerdown', (event) => { dragging = true; handle.setPointerCapture(event.pointerId); event.preventDefault(); });
  handle.addEventListener('pointermove', (event) => { if (!dragging) return; applyWidth(window.innerWidth - event.clientX); });
  handle.addEventListener('pointerup', (event) => { dragging = false; try { localStorage.setItem(storageKey, JSON.stringify({width})); } catch (_) {} handle.releasePointerCapture?.(event.pointerId); });
  handle.addEventListener('pointercancel', () => { dragging = false; });
}
"""
    component = st.components.v2.component("pricegauger_market_watchlist_v2", js=js, isolate_styles=False)
    component(key="pricegauger-market-watchlist-v2", data=payload, height=0)


def render_market_watchlist_v2() -> None:
    """Read-only progressive watchlist drawer; it never changes collection or execution authority."""
    markets = _safe_markets()
    if not markets:
        return
    previous = st.session_state.get(_WATCHLIST_KEY)
    default = [item for item in (previous or markets[:6]) if item in markets]
    with st.expander("Watchlist", expanded=False):
        selected = st.multiselect(
            "Markeder i watchlist",
            options=list(markets),
            default=default,
            key=_WATCHLIST_KEY,
            help="Kun presentasjon. Datainnsamling/subscription endres ikke.",
        )
        st.caption("Skuffen til høyre viser først pris og relativ endring. Dra den bredere for mikro-graf.")
    if not selected:
        return
    store = RealtimeMarketDataStore()
    _render_component(_series_for_market(store, market) for market in selected)


__all__ = ["render_market_watchlist_v2"]
