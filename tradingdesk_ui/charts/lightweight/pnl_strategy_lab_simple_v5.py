from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab import build_strategy_lab_payload_v1
from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_regime_v3 import _STRATEGY_LAB_REGIME_JS


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Strategy Lab v5 renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_STRATEGY_LAB_SIMPLE_JS = _STRATEGY_LAB_REGIME_JS

# The lab is deliberately one simple comparison plane for now: all baseline series are
# rebased to the visible window's left edge and therefore start at 0%. Range controls
# define the comparison start. This avoids mixing cumulative-history and regime semantics.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """        let comparisonView = 'total';\n        let rebasing = false;""",
    """        let comparisonView = 'relative';\n        let rebasing = false;""",
    label="always-relative state",
)

# Persist view state in the browser so component redraws caused by fresh P/L data do not
# throw the user back to the default 4h viewport or re-enable hidden comparison series.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """        const colors = theme();\n        parentElement.replaceChildren();""",
    """        const colors = theme();\n        const stateKey = `pg-strategy-lab-v5:${mode}:${String(payload.chart_id || 'default')}`;\n        window.__pricegaugerStrategyLabViewV5 = window.__pricegaugerStrategyLabViewV5 || {};\n        const savedView = window.__pricegaugerStrategyLabViewV5[stateKey] || { range: null, visibleByLabel: {} };\n        if (!savedView.visibleByLabel) savedView.visibleByLabel = {};\n        window.__pricegaugerStrategyLabViewV5[stateKey] = savedView;\n        function rememberView(range) {\n            const from = Number(range?.from);\n            const to = Number(range?.to);\n            if (Number.isFinite(from) && Number.isFinite(to) && from < to) {\n                savedView.range = { from, to };\n            }\n        }\n        parentElement.replaceChildren();""",
    label="persisted browser view state",
)

# Remove the Total/Relative mode buttons. The existing rebase machinery remains the
# single source of presentation truth and follows pan/zoom/range changes.
_start = """        if (mode === 'baseline') {\n            const totalButton = document.createElement('button');\n            const relativeButton = document.createElement('button');"""
_end = """        const maxTime = allTimes.filter(Number.isFinite).reduce((max, value) => Math.max(max, value), Number(payload.as_of || 0));"""
if _start not in _STRATEGY_LAB_SIMPLE_JS or _end not in _STRATEGY_LAB_SIMPLE_JS:
    raise RuntimeError("Strategy Lab v5 renderer anchor missing: comparison controls")
_prefix, _tail = _STRATEGY_LAB_SIMPLE_JS.split(_start, 1)
_controls, _suffix = _tail.split(_end, 1)
_STRATEGY_LAB_SIMPLE_JS = _prefix + """        chart.timeScale().subscribeVisibleTimeRangeChange((range) => {\n            rememberView(range);\n            applyComparisonView(range);\n        });\n\n        requestAnimationFrame(() => applyComparisonView());\n\n""" + _end + _suffix

# Restore the most recent zoom/pan window after a component redraw. Only use the default
# four-hour viewport on the first mount for this chart identity.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """        try {\n            chart.timeScale().setVisibleRange({ from: navigationEnd - (4 * 3600), to: navigationEnd });\n        } catch (_) {\n            chart.timeScale().fitContent();\n        }""",
    """        try {\n            const restored = savedView?.range;\n            const from = Number(restored?.from);\n            const to = Number(restored?.to);\n            if (Number.isFinite(from) && Number.isFinite(to) && from < to) {\n                chart.timeScale().setVisibleRange({ from, to });\n            } else {\n                chart.timeScale().setVisibleRange({ from: navigationEnd - (4 * 3600), to: navigationEnd });\n            }\n        } catch (_) {\n            chart.timeScale().fitContent();\n        }""",
    label="restore viewport",
)

# Persist per-series visibility as well. A fresh payload should update data, not reset the
# user's comparison choices.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """        function addLegend(api, label, color, defaultVisible = true) {\n            visible.set(api, defaultVisible);""",
    """        function addLegend(api, label, color, defaultVisible = true) {\n            const rememberedVisible = savedView.visibleByLabel[label];\n            const initialVisible = typeof rememberedVisible === 'boolean' ? rememberedVisible : defaultVisible;\n            visible.set(api, initialVisible);\n            try { api.applyOptions({ visible: initialVisible }); } catch (_) {}""",
    label="restore legend visibility",
)
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """                font: 'inherit', cursor: 'pointer', opacity: defaultVisible ? '1' : '.45',""",
    """                font: 'inherit', cursor: 'pointer', opacity: initialVisible ? '1' : '.45',""",
    label="restored legend opacity",
)
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """                visible.set(api, next);\n                try { api.applyOptions({ visible: next }); } catch (_) {}\n                item.style.opacity = next ? '1' : '.45';""",
    """                visible.set(api, next);\n                savedView.visibleByLabel[label] = next;\n                try { api.applyOptions({ visible: next }); } catch (_) {}\n                item.style.opacity = next ? '1' : '.45';""",
    label="persist legend visibility",
)

# Legend belongs below the plot and must be fully visible: wrap over as many lines as
# necessary instead of creating a private horizontal scroller.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """            display: 'flex', gap: '12px', alignItems: 'center', overflowX: 'auto',\n            whiteSpace: 'nowrap', padding: '7px 0 10px 0', color: colors.text,\n            font: '500 11px/1.3 system-ui,-apple-system,sans-serif', scrollbarWidth: 'thin',""",
    """            display: 'flex', gap: '8px 14px', alignItems: 'center', flexWrap: 'wrap',\n            overflow: 'visible', whiteSpace: 'normal', width: '100%', minWidth: '0',\n            padding: '8px 0 4px 0', color: colors.text,\n            font: '500 11px/1.3 system-ui,-apple-system,sans-serif',""",
    label="wrapped legend",
)

# Let legend items shrink/wrap naturally instead of forcing one unbreakable row.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """                display: 'inline-flex', gap: '6px', alignItems: 'center', flex: '0 0 auto',\n                border: '0', background: 'transparent', color: colors.text, padding: '1px 0',""",
    """                display: 'inline-flex', gap: '6px', alignItems: 'center', flex: '0 1 auto',\n                minWidth: '0', maxWidth: '100%', border: '0', background: 'transparent',\n                color: colors.text, padding: '1px 0',""",
    label="wrappable legend items",
)

# Make the benchmark heading a normal full-width block. There is no desktop header grid,
# so titles cannot be squeezed into a narrow left column.
_STRATEGY_LAB_SIMPLE_JS = _replace_required(
    _STRATEGY_LAB_SIMPLE_JS,
    """            color: colors.text, font: '700 14px/1.3 system-ui,-apple-system,sans-serif',\n            padding: '2px 0 6px 0',""",
    """            color: colors.text, font: '700 14px/1.3 system-ui,-apple-system,sans-serif',\n            width: '100%', minWidth: '0', padding: '2px 0 6px 0',""",
    label="full-width heading",
)


_strategy_lab_simple_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_simple_v5",
    js=_STRATEGY_LAB_SIMPLE_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v5(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    _strategy_lab_simple_component(
        key=f"{key}:baseline-simple-v5",
        data={"payload": payload, "mode": "baseline"},
        height=690,
    )


__all__ = ["_STRATEGY_LAB_SIMPLE_JS", "render_strategy_lab_pnl_v5"]
