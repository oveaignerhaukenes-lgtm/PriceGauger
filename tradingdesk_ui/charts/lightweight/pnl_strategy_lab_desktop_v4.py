from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import build_strategy_lab_payload_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_regime_v3 import _STRATEGY_LAB_REGIME_JS


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Strategy Lab v4 desktop renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_STRATEGY_LAB_DESKTOP_JS = _STRATEGY_LAB_REGIME_JS

# Desktop/web gets a denser information architecture while mobile keeps the proven v3
# layout and touch behavior unchanged.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        const colors = theme();\n        parentElement.replaceChildren();""",
    """        const colors = theme();\n        const desktopLayout = window.matchMedia('(min-width: 900px)').matches;\n        parentElement.replaceChildren();""",
    label="desktop breakpoint",
)

# Mark broker-provenance help text so the desktop header can move it together with the
# heading without depending on child indexes. Mobile leaves the DOM exactly where v3 did.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """            provenanceLegend.textContent = '● strategibytte · ■ MANUAL / SAXO = eksplisitt broker-provenance';\n            Object.assign(provenanceLegend.style,""",
    """            provenanceLegend.textContent = '● strategibytte · ■ MANUAL / SAXO = eksplisitt broker-provenance';\n            provenanceLegend.dataset.pgProvenance = '1';\n            Object.assign(provenanceLegend.style,""",
    label="provenance header marker",
)

# On wide screens put the clickable strategy legend to the right of the heading/help
# information. This frees the plot itself from carrying series identification.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        shell.appendChild(legend);\n\n        const chart = LWC.createChart(root,""",
    """        shell.appendChild(legend);\n\n        if (desktopLayout) {\n            const headerRow = document.createElement('div');\n            const headerInfo = document.createElement('div');\n            Object.assign(headerRow.style, {\n                display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(280px, auto)',\n                gap: '18px', alignItems: 'start', width: '100%', minWidth: '0',\n                padding: '2px 0 7px 0',\n            });\n            Object.assign(headerInfo.style, { minWidth: '0' });\n            headerInfo.appendChild(heading);\n            const provenanceNode = shell.querySelector('[data-pg-provenance="1"]');\n            if (provenanceNode) headerInfo.appendChild(provenanceNode);\n            Object.assign(legend.style, {\n                justifyContent: 'flex-end', justifySelf: 'end', maxWidth: '62vw',\n                padding: '1px 0 0 0', margin: '0',\n            });\n            headerRow.append(headerInfo, legend);\n            shell.insertBefore(headerRow, toolbar);\n        }\n\n        const chart = LWC.createChart(root,""",
    label="desktop header legend",
)

# Overlay layer for desktop event annotations. The chart series remains the source of
# truth; this is presentation-only and never changes P/L, provenance, or execution data.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        const labels = new Map();\n        const visible = new Map();""",
    """        const eventAnnotationLayer = document.createElement('div');\n        Object.assign(eventAnnotationLayer.style, {\n            position: 'absolute', inset: '0', zIndex: '7', pointerEvents: 'none',\n            overflow: 'hidden', display: desktopLayout ? 'block' : 'none',\n        });\n        root.appendChild(eventAnnotationLayer);\n\n        const labels = new Map();\n        const visible = new Map();""",
    label="desktop annotation layer",
)

_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        let rebasing = false;\n        let live = null;""",
    """        let rebasing = false;\n        let live = null;\n        let desktopEventCarrier = null;\n        let desktopLiveData = [];\n        let desktopLiveEvents = [];\n        let desktopAnnotationRaf = 0;""",
    label="desktop annotation state",
)

# Render event labels in lanes above the plot and draw a vertical leader to the exact
# event value/time. Nearby labels naturally stack downward instead of covering curves.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        function addLegend(api, label, color, defaultVisible = true) {""",
    """        function renderDesktopEventAnnotations() {\n            if (!desktopLayout || !desktopEventCarrier || !desktopLiveEvents.length) {\n                eventAnnotationLayer.replaceChildren();\n                return;\n            }\n            eventAnnotationLayer.replaceChildren();\n            const range = chart.timeScale().getVisibleRange();\n            if (!range) return;\n            const from = Number(range.from);\n            const to = Number(range.to);\n            const baseline = comparisonView === 'relative' ? baselineValue(desktopLiveData, from) : 0;\n            const rootWidth = root.clientWidth || 0;\n            const laneLastX = [];\n            const laneGap = 138;\n            const laneHeight = 22;\n\n            const events = desktopLiveEvents\n                .map((item) => ({ ...item, _time: Number(item.time), _value: Number(item.value) }))\n                .filter((item) => Number.isFinite(item._time) && Number.isFinite(item._value))\n                .filter((item) => item._time >= from && item._time <= to)\n                .sort((a, b) => a._time - b._time);\n\n            for (const item of events) {\n                const x = chart.timeScale().timeToCoordinate(item._time);\n                const plottedValue = item._value - baseline;\n                const y = desktopEventCarrier.priceToCoordinate(plottedValue);\n                if (!Number.isFinite(x) || !Number.isFinite(y)) continue;\n                if (x < -4 || x > rootWidth + 4) continue;\n\n                let lane = 0;\n                while (lane < laneLastX.length && x - laneLastX[lane] < laneGap) lane += 1;\n                laneLastX[lane] = x;\n                const labelTop = 5 + lane * laneHeight;\n                const labelX = Math.max(70, Math.min(rootWidth - 70, x));\n                const color = String(item.color || '#2563eb');\n\n                const leader = document.createElement('div');\n                const leaderTop = labelTop + 17;\n                const leaderBottom = Math.max(leaderTop + 7, Math.min(root.clientHeight - 4, y));\n                Object.assign(leader.style, {\n                    position: 'absolute', left: `${Math.round(x)}px`, top: `${leaderTop}px`,\n                    height: `${Math.max(7, leaderBottom - leaderTop)}px`, width: '0',\n                    borderLeft: `1px solid ${color}`, opacity: '.55',\n                });\n\n                const label = document.createElement('div');\n                label.textContent = String(item.label || 'event');\n                Object.assign(label.style, {\n                    position: 'absolute', left: `${Math.round(labelX)}px`, top: `${labelTop}px`,\n                    transform: 'translateX(-50%)', maxWidth: '132px', padding: '2px 5px',\n                    borderRadius: '4px', border: `1px solid ${color}`,\n                    background: colors.card, color, whiteSpace: 'nowrap', overflow: 'hidden',\n                    textOverflow: 'ellipsis', font: '700 9px/1.25 system-ui,-apple-system,sans-serif',\n                });\n                eventAnnotationLayer.append(leader, label);\n            }\n        }\n\n        function scheduleDesktopEventAnnotations() {\n            if (!desktopLayout) return;\n            if (desktopAnnotationRaf) cancelAnimationFrame(desktopAnnotationRaf);\n            desktopAnnotationRaf = requestAnimationFrame(() => {\n                desktopAnnotationRaf = 0;\n                renderDesktopEventAnnotations();\n            });\n        }\n\n        function addLegend(api, label, color, defaultVisible = true) {""",
    label="desktop event annotation renderer",
)

# Preserve raw LIVE data so event leaders follow the same baseline when Relative is on.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """            const liveData = Array.from(payload.live?.data || []);\n            live = chart.addSeries""",
    """            const liveData = Array.from(payload.live?.data || []);\n            desktopLiveData = liveData;\n            live = chart.addSeries""",
    label="desktop LIVE baseline data",
)

_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """                    carrier.setData(carrierData);\n                    comparableSeries.push({ api: carrier, data: carrierData, baselineData: liveData });""",
    """                    carrier.setData(carrierData);\n                    desktopEventCarrier = carrier;\n                    desktopLiveEvents = liveEvents;\n                    comparableSeries.push({ api: carrier, data: carrierData, baselineData: liveData });""",
    label="desktop event carrier registration",
)

# Mobile retains the current in-chart marker labels. Desktop keeps only the marker shape
# at the event point; the readable text lives in the stacked annotation lane above.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """                                text: String(item.label || ''),""",
    """                                text: desktopLayout ? '' : String(item.label || ''),""",
    label="desktop marker text suppression",
)

# Relative is the useful default for regime comparison on desktop. Mobile stays on Total
# by default to preserve its current compact interaction behavior.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """            styleModeButton(totalButton, true);\n            styleModeButton(relativeButton, false);\n            toolbar.append(totalButton, relativeButton);""",
    """            comparisonView = desktopLayout ? 'relative' : 'total';\n            styleModeButton(totalButton, comparisonView === 'total');\n            styleModeButton(relativeButton, comparisonView === 'relative');\n            toolbar.append(totalButton, relativeButton);\n            if (comparisonView === 'relative') requestAnimationFrame(() => applyComparisonView());""",
    label="desktop Relative default",
)

# A view toggle changes event Y coordinates even if time range is unchanged.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """                applyComparisonView();\n            };""",
    """                applyComparisonView();\n                scheduleDesktopEventAnnotations();\n            };""",
    label="annotation refresh on comparison toggle",
)

# Pan/zoom/resize keep annotation leaders attached to their event coordinates. This also
# applies to the lower Advanced chart, where the routine is a no-op because it has no
# LIVE provenance carrier.
_STRATEGY_LAB_DESKTOP_JS = _replace_required(
    _STRATEGY_LAB_DESKTOP_JS,
    """        chart.subscribeCrosshairMove((param) => {""",
    """        if (desktopLayout) {\n            chart.timeScale().subscribeVisibleTimeRangeChange(() => scheduleDesktopEventAnnotations());\n            if (typeof ResizeObserver !== 'undefined') {\n                const eventResizeObserver = new ResizeObserver(() => scheduleDesktopEventAnnotations());\n                eventResizeObserver.observe(root);\n            }\n            scheduleDesktopEventAnnotations();\n        }\n\n        chart.subscribeCrosshairMove((param) => {""",
    label="desktop annotation lifecycle",
)


_strategy_lab_desktop_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_desktop_v4",
    js=_STRATEGY_LAB_DESKTOP_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v4(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    _strategy_lab_desktop_component(
        key=f"{key}:baseline-desktop-v4",
        data={"payload": payload, "mode": "baseline"},
        height=640,
    )
    _strategy_lab_desktop_component(
        key=f"{key}:advanced-desktop-v4",
        data={"payload": payload, "mode": "advanced"},
        height=700,
    )


__all__ = ["_STRATEGY_LAB_DESKTOP_JS", "render_strategy_lab_pnl_v4"]
