from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import (
    _STRATEGY_LAB_JS,
    build_strategy_lab_payload_v1,
)


# Keep the persisted Strategy Lab read-model exactly as v1. This renderer-only adapter
# restores the original comparison semantics: market, LIVE and baseline controls share
# one relative-return pane so every series is read against the same 0% axis.
# Advanced/Spring panes retain their separate semantics.
_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_JS

_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_UNIFIED_JS.replace(
    """            live = chart.addSeries(LWC.LineSeries, {{\n                title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,\n                lineType: LWC.LineType?.WithSteps ?? 1,\n                priceLineVisible: false, lastValueVisible: false,\n            }}, 1);""",
    """            live = chart.addSeries(LWC.LineSeries, {{\n                title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,\n                lineType: LWC.LineType?.WithSteps ?? 1,\n                priceLineVisible: false, lastValueVisible: false,\n            }}, 0);""",
)
_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_UNIFIED_JS.replace(
    """                    const carrier = chart.addSeries(LWC.LineSeries, {{\n                        title: '', color: 'rgba(0,0,0,0)', lineWidth: 1,\n                        priceLineVisible: false, lastValueVisible: false,\n                        crosshairMarkerVisible: false,\n                    }}, 1);""",
    """                    const carrier = chart.addSeries(LWC.LineSeries, {{\n                        title: '', color: 'rgba(0,0,0,0)', lineWidth: 1,\n                        priceLineVisible: false, lastValueVisible: false,\n                        crosshairMarkerVisible: false,\n                    }}, 0);""",
)
_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_UNIFIED_JS.replace(
    """                const api = chart.addSeries(LWC.LineSeries, {{\n                    title: '', color: String(model.color || '#2563eb'), lineWidth: 2,\n                    lineStyle: lineStyle(String(model.dash || 'dash')),\n                    priceLineVisible: false, lastValueVisible: false,\n                }}, 2);""",
    """                const api = chart.addSeries(LWC.LineSeries, {{\n                    title: '', color: String(model.color || '#2563eb'), lineWidth: 2,\n                    lineStyle: lineStyle(String(model.dash || 'dash')),\n                    priceLineVisible: false, lastValueVisible: false,\n                }}, 0);""",
)

# On mobile the browser/Streamlit host can consume a two-finger gesture before
# Lightweight Charts gets the pinch. Preserve normal page vertical scrolling with one
# finger, but reserve multi-touch pinch for the chart's native handleScale.pinch path.
_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_UNIFIED_JS.replace(
    """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden',""",
    """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden', touchAction: 'pan-y',""",
)
_STRATEGY_LAB_UNIFIED_JS = _STRATEGY_LAB_UNIFIED_JS.replace(
    """        shell.appendChild(root);\n\n        const inspector = document.createElement('div');""",
    """        shell.appendChild(root);\n        root.addEventListener('touchmove', (event) => {{\n            if (event.touches?.length >= 2) event.preventDefault();\n        }}, {{ passive: false }});\n\n        const inspector = document.createElement('div');""",
)


_strategy_lab_unified_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_unified_v2",
    js=_STRATEGY_LAB_UNIFIED_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v2(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    _strategy_lab_unified_component(
        key=f"{key}:baseline-unified-v2",
        data={"payload": payload, "mode": "baseline"},
        height=640,
    )
    _strategy_lab_unified_component(
        key=f"{key}:advanced-unified-v2",
        data={"payload": payload, "mode": "advanced"},
        height=700,
    )


__all__ = ["render_strategy_lab_pnl_v2"]
