from __future__ import annotations

import hashlib
from typing import Any, Sequence

import streamlit as st


_MARKER_OVERLAY_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const chartId = String(data.chart_id || '');
    const registry = window.__pricegaugerLightweightCharts;
    const timers = [];

    function nearestTime(times, raw) {
        if (!times.length) return null;
        let best = times[0];
        let distance = Math.abs(best - raw);
        for (const value of times) {
            const next = Math.abs(value - raw);
            if (next < distance) {
                best = value;
                distance = next;
            }
        }
        return best;
    }

    function payload(entry) {
        const times = Array.from(entry?.baseCandles?.keys?.() || [])
            .map(Number).filter(Number.isFinite).sort((a, b) => a - b);
        if (!times.length) return [];
        const grace = Math.max(60, Number(data.timeframe_seconds || 60));
        const first = times[0];
        const last = times[times.length - 1];
        return Array.from(data.trade_markers || []).flatMap((marker, index) => {
            const raw = Number(marker.executed_at);
            const price = Number(marker.execution_price);
            const direction = String(marker.direction || '').toUpperCase();
            if (!Number.isFinite(raw) || !Number.isFinite(price)) return [];
            if (!['LONG', 'SHORT', 'FLAT'].includes(direction)) return [];
            if (raw < first - grace || raw > last + grace) return [];
            const time = nearestTime(times, raw);
            if (time == null) return [];
            const isFlat = direction === 'FLAT';
            return [{
                time,
                price,
                position: 'atPriceMiddle',
                shape: isFlat ? 'square' : (direction === 'LONG' ? 'arrowUp' : 'arrowDown'),
                color: isFlat ? '#64748b' : (direction === 'LONG' ? '#0ea5e9' : '#f59e0b'),
                size: isFlat ? 1.0 : (marker.active ? 1.0 : 0.72),
                id: `${marker.id || raw}:${index}`,
            }];
        });
    }

    function apply() {
        const entry = registry?.get?.(chartId);
        if (!entry?.markers?.setMarkers || !entry?.baseCandles) return false;
        try {
            entry.markers.setMarkers(payload(entry));
            return true;
        } catch (_) {
            return false;
        }
    }

    // The normal 1s live updater and this presentation-only overlay are mounted in
    // the same fragment. Repeat briefly so the combined LONG/SHORT/FLAT payload wins
    // even when Streamlit/browser scheduling mounts the legacy updater a little later.
    [0, 80, 240, 700].forEach((delay) => {
        timers.push(window.setTimeout(apply, delay));
    });
    parentElement.style.display = 'none';
    return () => timers.forEach((timer) => window.clearTimeout(timer));
}
"""


_marker_overlay_component = st.components.v2.component(
    "pricegauger_lightweight_trade_marker_overlay_v2",
    js=_MARKER_OVERLAY_JS,
    isolate_styles=False,
)


def _safe_key(chart_id: str, revision: str) -> str:
    raw = f"{chart_id}\0{revision}".encode("utf-8")
    digest = hashlib.blake2s(raw, digest_size=16).hexdigest()
    return f"pg-lightweight-marker-overlay-{digest}"


def render_trade_marker_overlay_v2(
    *,
    chart_id: str,
    timeframe_seconds: int,
    trade_markers: Sequence[dict[str, Any]],
    revision: str,
) -> None:
    _marker_overlay_component(
        key=_safe_key(str(chart_id), str(revision)),
        data={
            "chart_id": str(chart_id),
            "timeframe_seconds": int(timeframe_seconds),
            "trade_markers": list(trade_markers),
        },
        height=0,
    )


__all__ = ["render_trade_marker_overlay_v2"]
