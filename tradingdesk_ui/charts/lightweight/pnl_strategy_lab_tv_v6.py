from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import build_strategy_lab_payload_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_simple_v5 import _STRATEGY_LAB_SIMPLE_JS
from tradingdesk_ui.charts.lightweight.data_revision_v1 import chart_data_revision_key_v1


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Strategy Lab TV v6 renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_STRATEGY_LAB_TV_JS = _STRATEGY_LAB_SIMPLE_JS
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """        window.__pricegaugerStrategyLabViewV5 = window.__pricegaugerStrategyLabViewV5 || {};\n        const savedView = window.__pricegaugerStrategyLabViewV5[stateKey] || { range: null, visibleByLabel: {} };\n        if (!savedView.visibleByLabel) savedView.visibleByLabel = {};\n        window.__pricegaugerStrategyLabViewV5[stateKey] = savedView;\n        function rememberView(range) {""",
    """        window.__pricegaugerStrategyLabViewV5 = window.__pricegaugerStrategyLabViewV5 || {};\n        const storageKey = `${stateKey}:workspace`;\n        let durableView = null;\n        try { durableView = JSON.parse(window.localStorage.getItem(storageKey) || 'null'); } catch (_) {}\n        const savedView = window.__pricegaugerStrategyLabViewV5[stateKey] || durableView || { range: null, visibleByLabel: {}, height: 560 };\n        if (!savedView.visibleByLabel) savedView.visibleByLabel = {};\n        if (!Number.isFinite(Number(savedView.height))) savedView.height = 560;\n        window.__pricegaugerStrategyLabViewV5[stateKey] = savedView;\n        function persistView() { try { window.localStorage.setItem(storageKey, JSON.stringify(savedView)); } catch (_) {} }\n        function rememberView(range) {""",
    label="durable workspace state",
)
_STRATEGY_LAB_TV_JS = _replace_required(_STRATEGY_LAB_TV_JS, """                savedView.range = { from, to };\n            }\n        }""", """                savedView.range = { from, to };\n                persistView();\n            }\n        }""", label="persist viewport")
_STRATEGY_LAB_TV_JS = _replace_required(_STRATEGY_LAB_TV_JS, """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden',""", """            width: '100%', height: `${Math.max(360, Math.min(820, Number(savedView.height) || 560))}px`,\n            position: 'relative', minWidth: '0', overflow: 'hidden',""", label="persistent chart height")
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """        const chart = LWC.createChart(root, {\n            autoSize: true,""",
    """        const osloClock = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', hour: '2-digit', minute: '2-digit', hour12: false });\n        const osloDateTime = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });\n        const chart = LWC.createChart(root, {\n            autoSize: true,\n            localization: { timeFormatter: time => osloDateTime.format(new Date(Number(time) * 1000)) },""",
    label="Oslo localization",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """                rightOffset: 1, barSpacing: 7, minBarSpacing: .8,""",
    """                rightOffset: 1, barSpacing: 7, minBarSpacing: .8,\n                tickMarkFormatter: time => osloClock.format(new Date(Number(time) * 1000)),""",
    label="Oslo tick marks",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """        shell.appendChild(root);\n\n        const inspector = document.createElement('div');""",
    """        shell.appendChild(root);\n        const resizeHandle = document.createElement('div');\n        resizeHandle.title = 'Dra for å endre høyden';\n        Object.assign(resizeHandle.style, {height:'12px',width:'100%',cursor:'ns-resize',touchAction:'none',display:'flex',alignItems:'center',justifyContent:'center',userSelect:'none'});\n        const resizeGrip=document.createElement('div'); Object.assign(resizeGrip.style,{width:'46px',height:'3px',borderRadius:'99px',background:colors.border}); resizeHandle.appendChild(resizeGrip); shell.appendChild(resizeHandle);\n        resizeHandle.addEventListener('pointerdown',(event)=>{event.preventDefault();resizeHandle.setPointerCapture?.(event.pointerId);const startY=event.clientY,startHeight=root.getBoundingClientRect().height;const move=(e)=>{const next=Math.max(360,Math.min(820,startHeight+e.clientY-startY));root.style.height=`${Math.round(next)}px`;savedView.height=Math.round(next);};const finish=()=>{persistView();resizeHandle.removeEventListener('pointermove',move);resizeHandle.removeEventListener('pointerup',finish);resizeHandle.removeEventListener('pointercancel',finish);};resizeHandle.addEventListener('pointermove',move);resizeHandle.addEventListener('pointerup',finish);resizeHandle.addEventListener('pointercancel',finish);});\n\n        const inspector = document.createElement('div');""",
    label="drag resize handle",
)
_STRATEGY_LAB_TV_JS = _replace_required(_STRATEGY_LAB_TV_JS, """                savedView.visibleByLabel[label] = next;\n                try { api.applyOptions({ visible: next }); } catch (_) {}""", """                savedView.visibleByLabel[label] = next;\n                persistView();\n                try { api.applyOptions({ visible: next }); } catch (_) {}""", label="persist legend choice")

_strategy_lab_tv_component = st.components.v2.component("pricegauger_lightweight_strategy_lab_tv_v6", js=_STRATEGY_LAB_TV_JS, isolate_styles=False)


def render_strategy_lab_pnl_v6(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    payload["baseline_models"] = list(payload.get("baseline_models") or []) + list(payload.get("advanced_models") or [])
    _strategy_lab_tv_component(key=chart_data_revision_key_v1("pg-strategy-lab-tv-v6", key, payload), data={"payload": payload, "mode": "baseline"}, height=930)


__all__ = ["_STRATEGY_LAB_TV_JS", "render_strategy_lab_pnl_v6"]
