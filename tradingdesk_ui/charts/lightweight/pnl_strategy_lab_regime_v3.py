from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import (
    _STRATEGY_LAB_JS,
    build_strategy_lab_payload_v1,
)


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Strategy Lab v3 renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_STRATEGY_LAB_REGIME_JS = _STRATEGY_LAB_JS

# Baseline comparison is one common percentage-return plane.
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """            live = chart.addSeries(LWC.LineSeries, {\n                title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,\n                lineType: LWC.LineType?.WithSteps ?? 1,\n                priceLineVisible: false, lastValueVisible: false,\n            }, 1);""",
    """            live = chart.addSeries(LWC.LineSeries, {\n                title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,\n                lineType: LWC.LineType?.WithSteps ?? 1,\n                priceLineVisible: false, lastValueVisible: false,\n            }, 0);""",
    label="LIVE pane",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """                    const carrier = chart.addSeries(LWC.LineSeries, {\n                        title: '', color: 'rgba(0,0,0,0)', lineWidth: 1,\n                        priceLineVisible: false, lastValueVisible: false,\n                        crosshairMarkerVisible: false,\n                    }, 1);""",
    """                    const carrier = chart.addSeries(LWC.LineSeries, {\n                        title: '', color: 'rgba(0,0,0,0)', lineWidth: 1,\n                        priceLineVisible: false, lastValueVisible: false,\n                        crosshairMarkerVisible: false,\n                    }, 0);""",
    label="provenance carrier pane",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """                const api = chart.addSeries(LWC.LineSeries, {\n                    title: '', color: String(model.color || '#2563eb'), lineWidth: 2,\n                    lineStyle: lineStyle(String(model.dash || 'dash')),\n                    priceLineVisible: false, lastValueVisible: false,\n                }, 2);""",
    """                const api = chart.addSeries(LWC.LineSeries, {\n                    title: '', color: String(model.color || '#2563eb'), lineWidth: 2,\n                    lineStyle: lineStyle(String(model.dash || 'dash')),\n                    priceLineVisible: false, lastValueVisible: false,\n                }, 0);""",
    label="baseline model pane",
)

# Mobile: reserve two-finger gestures for Lightweight Charts while one-finger vertical
# scrolling remains available to the page.
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden',""",
    """            width: '100%', height: mode === 'baseline' ? '560px' : '620px',\n            position: 'relative', minWidth: '0', overflow: 'hidden', touchAction: 'pan-y',""",
    label="mobile touch action",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """        shell.appendChild(root);\n\n        const inspector = document.createElement('div');""",
    """        shell.appendChild(root);\n        root.addEventListener('touchmove', (event) => {\n            if (event.touches?.length >= 2) event.preventDefault();\n        }, { passive: false });\n\n        const inspector = document.createElement('div');""",
    label="mobile pinch reservation",
)

# Lightweight Charts constrains visible ranges to its rendered time domain. Add a
# transparent whitespace-only carrier so short Strategy Series history does not clamp
# 12h/1d/3d/Alt or pinch zoom-out. It contains no price/P&L values.
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """        const labels = new Map();\n        const visible = new Map();\n        const allTimes = [];""",
    """        const navigationEnd = Number(payload.as_of || Math.floor(Date.now() / 1000));\n        const navigationStart = navigationEnd - (3 * 86400);\n        const navigationCarrier = chart.addSeries(LWC.LineSeries, {\n            title: '', color: 'rgba(0,0,0,0)', lineWidth: 1,\n            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,\n        }, 0);\n        navigationCarrier.setData([{ time: navigationStart }, { time: navigationEnd }]);\n\n        const labels = new Map();\n        const visible = new Map();\n        const allTimes = [];\n        const comparableSeries = [];\n        let comparisonView = 'total';\n        let rebasing = false;""",
    label="navigation and comparison state",
)

# Keep immutable raw data for every baseline comparison series. The provenance carrier
# follows LIVE's baseline so its markers remain aligned when the chart is rebased.
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """            market.setData(marketData);\n            labels.set(market, String(payload.market?.label || 'Marked'));""",
    """            market.setData(marketData);\n            comparableSeries.push({ api: market, data: marketData, baselineData: marketData });\n            labels.set(market, String(payload.market?.label || 'Marked'));""",
    label="market comparison registration",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """            live.setData(liveData);\n            labels.set(live, String(payload.live?.label || 'LIVE'));""",
    """            live.setData(liveData);\n            comparableSeries.push({ api: live, data: liveData, baselineData: liveData });\n            labels.set(live, String(payload.live?.label || 'LIVE'));""",
    label="LIVE comparison registration",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """                    carrier.setData(carrierData);\n                    rememberTimes(carrierData);""",
    """                    carrier.setData(carrierData);\n                    comparableSeries.push({ api: carrier, data: carrierData, baselineData: liveData });\n                    rememberTimes(carrierData);""",
    label="provenance comparison registration",
)
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """                api.setData(Array.from(model.data || []));\n                labels.set(api, String(model.label || 'Control'));""",
    """                const modelData = Array.from(model.data || []);\n                api.setData(modelData);\n                comparableSeries.push({ api, data: modelData, baselineData: modelData });\n                labels.set(api, String(model.label || 'Control'));""",
    label="baseline model comparison registration",
)

# Total = persisted cumulative return. Relative = percentage-point movement from each
# series' own value at the visible window's left edge. This deliberately answers a
# regime question rather than erasing the total-history view: which strategy is moving
# fastest in the window we are inspecting, regardless of old P/L baggage?
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """        const maxTime = allTimes.filter(Number.isFinite).reduce((max, value) => Math.max(max, value), Number(payload.as_of || 0));\n        const ranges = [""",
    """        function baselineValue(points, from) {\n            const data = Array.from(points || []);\n            if (!data.length) return 0;\n            let chosen = null;\n            for (const point of data) {\n                const time = Number(point.time);\n                const value = Number(point.value);\n                if (!Number.isFinite(time) || !Number.isFinite(value)) continue;\n                if (time <= from) chosen = value;\n                else {\n                    if (chosen == null) chosen = value;\n                    break;\n                }\n            }\n            return Number.isFinite(chosen) ? chosen : 0;\n        }\n\n        function rebasePoints(points, baseline) {\n            return Array.from(points || []).map((point) => {\n                const value = Number(point.value);\n                return Number.isFinite(value) ? { ...point, value: value - baseline } : point;\n            });\n        }\n\n        function applyComparisonView(range = chart.timeScale().getVisibleRange()) {\n            if (rebasing) return;\n            rebasing = true;\n            try {\n                const from = Number(range?.from ?? navigationStart);\n                for (const item of comparableSeries) {\n                    if (comparisonView === 'relative') {\n                        const baseline = baselineValue(item.baselineData, from);\n                        item.api.setData(rebasePoints(item.data, baseline));\n                    } else {\n                        item.api.setData(item.data);\n                    }\n                }\n            } finally {\n                rebasing = false;\n            }\n        }\n\n        if (mode === 'baseline') {\n            const totalButton = document.createElement('button');\n            const relativeButton = document.createElement('button');\n            totalButton.type = relativeButton.type = 'button';\n            totalButton.textContent = 'Total';\n            relativeButton.textContent = 'Relativ';\n            const styleModeButton = (button, active) => {\n                Object.assign(button.style, {\n                    flex: '0 0 auto', border: `1px solid ${colors.border}`, borderRadius: '7px',\n                    background: active ? colors.text : 'transparent',\n                    color: active ? colors.bg : colors.text, padding: '3px 9px',\n                    font: '700 11px/1.25 system-ui,-apple-system,sans-serif', cursor: 'pointer',\n                });\n            };\n            const selectView = (next) => {\n                comparisonView = next;\n                styleModeButton(totalButton, next === 'total');\n                styleModeButton(relativeButton, next === 'relative');\n                applyComparisonView();\n            };\n            totalButton.addEventListener('click', () => selectView('total'));\n            relativeButton.addEventListener('click', () => selectView('relative'));\n            styleModeButton(totalButton, true);\n            styleModeButton(relativeButton, false);\n            toolbar.append(totalButton, relativeButton);\n            chart.timeScale().subscribeVisibleTimeRangeChange((range) => {\n                if (comparisonView === 'relative') applyComparisonView(range);\n            });\n        }\n\n        const maxTime = allTimes.filter(Number.isFinite).reduce((max, value) => Math.max(max, value), Number(payload.as_of || 0));\n        const ranges = [""",
    label="total-relative controls",
)

# Default to a useful live four-hour viewport. Larger range controls now operate inside
# the explicit three-day time domain.
_STRATEGY_LAB_REGIME_JS = _replace_required(
    _STRATEGY_LAB_REGIME_JS,
    """        chart.timeScale().fitContent();""",
    """        try {\n            chart.timeScale().setVisibleRange({ from: navigationEnd - (4 * 3600), to: navigationEnd });\n        } catch (_) {\n            chart.timeScale().fitContent();\n        }""",
    label="initial four-hour viewport",
)


_strategy_lab_regime_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_regime_v3",
    js=_STRATEGY_LAB_REGIME_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v3(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    _strategy_lab_regime_component(
        key=f"{key}:baseline-regime-v3",
        data={"payload": payload, "mode": "baseline"},
        height=640,
    )
    _strategy_lab_regime_component(
        key=f"{key}:advanced-regime-v3",
        data={"payload": payload, "mode": "advanced"},
        height=700,
    )


__all__ = ["_STRATEGY_LAB_REGIME_JS", "render_strategy_lab_pnl_v3"]
