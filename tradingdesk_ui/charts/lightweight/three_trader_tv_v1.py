from __future__ import annotations

import streamlit as st


_THREE_TRADER_TV_JS = r"""
export default function(component) {
    const { data } = component;
    const payload = data.payload || {};
    const stateKey = data.state_key || 'three-trader';
    const storageKey = `${stateKey}:tv-workspace-v1`;
    let saved = { range: null, height: 430 };
    try { saved = Object.assign(saved, JSON.parse(window.localStorage.getItem(storageKey) || '{}')); } catch (_) {}
    const persist = () => { try { window.localStorage.setItem(storageKey, JSON.stringify(saved)); } catch (_) {} };
    const osloClock = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', hour: '2-digit', minute: '2-digit', hour12: false });
    const osloDateTime = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    const asDate = time => new Date(Number(time) * 1000);

    const shell = document.createElement('div');
    shell.style.width = '100%'; shell.style.minWidth = '0';
    const root = document.createElement('div');
    root.style.width = '100%'; root.style.height = `${Math.max(320, Math.min(820, Number(saved.height)||430))}px`;
    root.style.position = 'relative'; root.style.overflow = 'hidden'; shell.appendChild(root);

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js';
    script.onload = () => {
        const L = window.LightweightCharts;
        const chart = L.createChart(root, {
            autoSize: true,
            layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#334155' },
            localization: { timeFormatter: time => osloDateTime.format(asDate(time)) },
            grid: { vertLines: { color: '#eef2f7' }, horzLines: { color: '#eef2f7' } },
            rightPriceScale: { borderVisible: true, autoScale: true },
            timeScale: { borderVisible: true, timeVisible: true, secondsVisible: false, rightOffset: 3, tickMarkFormatter: time => osloClock.format(asDate(time)) },
            handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
            kineticScroll: { mouse: true, touch: true }, crosshair: { mode: 1 },
        });
        const price = chart.addSeries(L.LineSeries, { lineWidth: 2, title: 'Pris' });
        price.setData((payload.price || []).map(p => ({ time: p.time, value: p.value })));
        const markers = [];
        for (const event of (payload.events || [])) markers.push({ time: event.time, position: event.target > 0 ? 'belowBar' : 'aboveBar', shape: event.target > 0 ? 'arrowUp' : 'arrowDown', color: event.color, text: event.short, size: event.size || 1 });
        markers.sort((a,b) => a.time - b.time); if (L.createSeriesMarkers) L.createSeriesMarkers(price, markers);
        if (saved.range) { try { chart.timeScale().setVisibleLogicalRange(saved.range); } catch (_) {} } else chart.timeScale().fitContent();
        chart.timeScale().subscribeVisibleLogicalRangeChange(range => { if (range) { saved.range = range; persist(); } });
    };
    document.head.appendChild(script);

    const handle = document.createElement('div'); handle.title = 'Dra for å endre høyden';
    Object.assign(handle.style, {height:'12px', width:'100%', cursor:'ns-resize', touchAction:'none', display:'flex', alignItems:'center', justifyContent:'center', userSelect:'none'});
    const grip = document.createElement('div'); Object.assign(grip.style, {width:'46px', height:'3px', borderRadius:'99px', background:'#cbd5e1'}); handle.appendChild(grip); shell.appendChild(handle);
    handle.addEventListener('pointerdown', event => {
        event.preventDefault(); handle.setPointerCapture?.(event.pointerId); const startY=event.clientY, startHeight=root.getBoundingClientRect().height;
        const move=e=>{const next=Math.max(320,Math.min(820,startHeight+e.clientY-startY));root.style.height=`${Math.round(next)}px`;saved.height=Math.round(next);};
        const done=()=>{persist();handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',done);handle.removeEventListener('pointercancel',done);};
        handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',done);handle.addEventListener('pointercancel',done);
    });
    return shell;
}
"""

_three_trader_tv_component = st.components.v2.component("pricegauger_three_trader_tv_v1", js=_THREE_TRADER_TV_JS, isolate_styles=False)


def render_three_trader_tv_v1(price_frame, event_sets, visible_models, *, key: str) -> None:
    price = [{"time": int(item.timestamp()), "value": float(row["PRICE"])} for item, row in price_frame.iterrows()]
    colors = {"Dum MACD": "#2563eb", "MACD-adaptiv": "#16a34a", "Holistisk AI": "#dc2626"}
    shorts = {"Dum MACD": "Rule", "MACD-adaptiv": "Adaptiv", "Holistisk AI": "AI"}; sizes = {"Dum MACD": 1, "MACD-adaptiv": 2, "Holistisk AI": 3}; events = []
    for model, model_events in event_sets.items():
        if model not in visible_models: continue
        for event in model_events: events.append({"time": int(event["at"].timestamp()), "target": int(event["target"]), "color": colors.get(model, "#64748b"), "short": shorts.get(model, model), "size": sizes.get(model, 1)})
    _three_trader_tv_component(key=f"{key}:three-trader-tv-v1", data={"payload": {"price": price, "events": events}, "state_key": key}, height=850)


__all__ = ["_THREE_TRADER_TV_JS", "render_three_trader_tv_v1"]
