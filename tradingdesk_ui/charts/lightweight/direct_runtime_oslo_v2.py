from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from .direct_runtime import _DIRECT_LIVE_JS


def _replace_required(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"direct live Oslo renderer anchor missing: {label}")
    return source.replace(old, new, 1)


_DIRECT_LIVE_OSLO_JS = _replace_required(
    _DIRECT_LIVE_JS,
    """        const chart = LWC.createChart(root, {\n            autoSize: true,""",
    """        const osloClock = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', hour: '2-digit', minute: '2-digit', hour12: false });\n        const osloDateTime = new Intl.DateTimeFormat('nb-NO', { timeZone: 'Europe/Oslo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });\n        const chart = LWC.createChart(root, {\n            autoSize: true,\n            localization: { timeFormatter: time => osloDateTime.format(new Date(Number(time) * 1000)) },""",
    "chart localization",
)
_DIRECT_LIVE_OSLO_JS = _replace_required(
    _DIRECT_LIVE_OSLO_JS,
    """                rightOffset: 3, barSpacing: 11, minBarSpacing: 2.5,\n                fixLeftEdge: false, fixRightEdge: false,""",
    """                rightOffset: 3, barSpacing: 11, minBarSpacing: 2.5,\n                tickMarkFormatter: time => osloClock.format(new Date(Number(time) * 1000)),\n                fixLeftEdge: false, fixRightEdge: false,""",
    "time-axis localization",
)

_direct_live_oslo_component = st.components.v2.component(
    "pricegauger_tradingdesk_lightweight_direct_live_oslo_v2",
    js=_DIRECT_LIVE_OSLO_JS,
    isolate_styles=False,
)


def render_lightweight_direct_live_oslo_v2(
    payload: Mapping[str, Any],
    *,
    key: str,
) -> None:
    height = max(320, int(payload.get("height", 780)))
    _direct_live_oslo_component(
        key=str(key),
        data={"payload": dict(payload)},
        height=height,
    )


__all__ = ["_DIRECT_LIVE_OSLO_JS", "render_lightweight_direct_live_oslo_v2"]
