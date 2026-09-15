from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import build_strategy_lab_payload_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_simple_v5 import _STRATEGY_LAB_SIMPLE_JS


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Strategy Lab TV v6 renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_STRATEGY_LAB_TV_JS = _STRATEGY_LAB_SIMPLE_JS

# Persist viewport, legend choices and chart height across full browser reloads. v5 kept
# these only for component redraws; v6 makes the TradingView-like workspace durable.
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """        window.__pricegaugerStrategyLabViewV5 = window.__pricegaugerStrategyLabViewV5 || {};\n        const savedView = window.__pricegaugerStrategyLabViewV5[stateKey] || { range: null, visibleByLabel: {} };\n        if (!savedView.visibleByLabel) savedView.visibleByLabel = {};\n        window.__pricegaugerStrategyLabViewV5[stateKey] = savedView;\n        function rememberView(range) {""",
    """        window.__pricegaugerStrategyLabViewV5 = window.__pricegaugerStrategyLabViewV5 || {};\n        const storageKey = `${stateKey}:workspace`;\n        let durableView = null;\n        try { durableView = JSON.parse(window.localStorage.getItem(storageKey) || 'null'); } catch (_) {}\n        const savedView = window.__pricegaugerStrategyLabViewV5[stateKey] || durableView || { range: null, visibleByLabel: {}, height: 560 };\n        if (!savedView.visibleByLabel) savedView.visibleByLabel = {};\n        if (!Number.isFinite(Number(savedView.height))) savedView.height = 560;\n        window.__pricegaugerStrategyLabViewV5[stateKey] = savedView;\n        function persistView() {\n            try { window.localStorage.setItem(storageKey, JSON.stringify(savedView)); } catch (_) {}\n        }\n        function rememberView(range) {""",
    label="durable workspace state",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """                savedView.range = { from, to };\n            }\n        }""",
    """                savedView.range = { from, to };\n                persistView();\n            }\n        }""",
    label="persist viewport",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden',""",
    """            width: '100%', height: `${Math.max(360, Math.min(820, Number(savedView.height) || 560))}px`,\n            position: 'relative', minWidth: '0', overflow: 'hidden',""",
    label="persistent chart height",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """        shell.appendChild(root);\n\n        const inspector = document.createElement('div');""",
    """        shell.appendChild(root);\n\n        const resizeHandle = document.createElement('div');\n        resizeHandle.title = 'Dra for å endre høyden';\n        Object.assign(resizeHandle.style, {\n            height: '12px', width: '100%', cursor: 'ns-resize', touchAction: 'none',\n            display: 'flex', alignItems: 'center', justifyContent: 'center', userSelect: 'none',\n        });\n        const resizeGrip = document.createElement('div');\n        Object.assign(resizeGrip.style, { width: '46px', height: '3px', borderRadius: '99px', background: colors.border });\n        resizeHandle.appendChild(resizeGrip);\n        shell.appendChild(resizeHandle);\n        resizeHandle.addEventListener('pointerdown', (event) => {\n            event.preventDefault();\n            resizeHandle.setPointerCapture?.(event.pointerId);\n            const startY = event.clientY;\n            const startHeight = root.getBoundingClientRect().height;\n            const move = (moveEvent) => {\n                const next = Math.max(360, Math.min(820, startHeight + moveEvent.clientY - startY));\n                root.style.height = `${Math.round(next)}px`;\n                savedView.height = Math.round(next);\n            };\n            const finish = () => {\n                persistView();\n                resizeHandle.removeEventListener('pointermove', move);\n                resizeHandle.removeEventListener('pointerup', finish);\n                resizeHandle.removeEventListener('pointercancel', finish);\n            };\n            resizeHandle.addEventListener('pointermove', move);\n            resizeHandle.addEventListener('pointerup', finish);\n            resizeHandle.addEventListener('pointercancel', finish);\n        });\n\n        const inspector = document.createElement('div');""",
    label="drag resize handle",
)
_STRATEGY_LAB_TV_JS = _replace_required(
    _STRATEGY_LAB_TV_JS,
    """                savedView.visibleByLabel[label] = next;\n                try { api.applyOptions({ visible: next }); } catch (_) {}""",
    """                savedView.visibleByLabel[label] = next;\n                persistView();\n                try { api.applyOptions({ visible: next }); } catch (_) {}""",
    label="persist legend choice",
)


_strategy_lab_tv_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_tv_v6",
    js=_STRATEGY_LAB_TV_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v6(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    payload["baseline_models"] = list(payload.get("baseline_models") or []) + list(
        payload.get("advanced_models") or []
    )
    _strategy_lab_tv_component(
        key=f"{key}:strategy-lab-tv-v6",
        data={"payload": payload, "mode": "baseline"},
        height=930,
    )


__all__ = ["_STRATEGY_LAB_TV_JS", "render_strategy_lab_pnl_v6"]
