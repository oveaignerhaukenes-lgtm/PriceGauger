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

# Remove the Total/Relative mode buttons. The existing rebase machinery remains the
# single source of presentation truth and follows pan/zoom/range changes.
_start = """        if (mode === 'baseline') {\n            const totalButton = document.createElement('button');\n            const relativeButton = document.createElement('button');"""
_end = """        const maxTime = allTimes.filter(Number.isFinite).reduce((max, value) => Math.max(max, value), Number(payload.as_of || 0));"""
if _start not in _STRATEGY_LAB_SIMPLE_JS or _end not in _STRATEGY_LAB_SIMPLE_JS:
    raise RuntimeError("Strategy Lab v5 renderer anchor missing: comparison controls")
_prefix, _tail = _STRATEGY_LAB_SIMPLE_JS.split(_start, 1)
_controls, _suffix = _tail.split(_end, 1)
_STRATEGY_LAB_SIMPLE_JS = _prefix + """        chart.timeScale().subscribeVisibleTimeRangeChange((range) => {\n            applyComparisonView(range);\n        });\n\n        requestAnimationFrame(() => applyComparisonView());\n\n""" + _end + _suffix

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
