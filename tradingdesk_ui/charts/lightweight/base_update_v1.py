from __future__ import annotations

import hashlib
from typing import Any, Mapping

import streamlit as st


_BASE_UPDATE_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const payload = data.payload || {};
    const chartId = String(payload.chart_id || '');
    const registry = window.__pricegaugerLightweightCharts;
    let retryTimer = null;

    function mergedForming(entry, item) {
        const time = Number(item.time);
        const base = entry.baseCandles?.get?.(time) || null;
        return {
            time,
            open: base ? Number(base.open) : Number(item.open),
            high: Math.max(Number(item.high), base ? Number(base.high) : Number(item.high)),
            low: Math.min(Number(item.low), base ? Number(base.low) : Number(item.low)),
            close: Number(item.close),
        };
    }

    function apply() {
        const entry = registry?.get?.(chartId) || null;
        if (!entry?.candles) return false;

        const candleData = Array.from(payload.candles || []);
        entry.baseCandles = new Map(
            candleData.map((item) => [Number(item.time), { ...item }])
        );
        try { entry.candles.setData(candleData); } catch (_) {}

        if (entry.formingCandles instanceof Map) {
            for (const item of entry.formingCandles.values()) {
                try { entry.candles.update(mergedForming(entry, item)); } catch (_) {}
            }
        }

        for (const item of Array.from(payload.lines || [])) {
            try {
                entry.series?.get?.(String(item.role))?.setData?.(Array.from(item.data || []));
            } catch (_) {}
        }
        for (const item of Array.from(payload.histograms || [])) {
            try {
                entry.series?.get?.(String(item.role))?.setData?.(
                    Array.from(item.data || []).map((point) => ({
                        time: point.time,
                        value: point.value,
                        color: Number(point.value) >= 0
                            ? 'rgba(22,163,74,.34)'
                            : 'rgba(220,38,38,.34)',
                    }))
                );
            } catch (_) {}
        }

        const volume = entry.series?.get?.('volume');
        if (volume) {
            try {
                volume.setData(Array.from(payload.volume || []).map((point) => ({
                    time: point.time,
                    value: point.value,
                    color: point.direction === 'up'
                        ? 'rgba(22,163,74,.28)'
                        : 'rgba(220,38,38,.28)',
                })));
            } catch (_) {}
        }
        return true;
    }

    if (!apply()) {
        let attempts = 0;
        retryTimer = window.setInterval(() => {
            attempts += 1;
            if (apply() || attempts >= 20) {
                window.clearInterval(retryTimer);
                retryTimer = null;
            }
        }, 100);
    }

    parentElement.style.display = 'none';
    return () => {
        if (retryTimer) window.clearInterval(retryTimer);
    };
}
"""


_base_update_component = st.components.v2.component(
    "pricegauger_tradingdesk_lightweight_base_update_v1",
    js=_BASE_UPDATE_JS,
    isolate_styles=False,
)


def _last_point(series: object) -> str:
    values = list(series or [])
    if not values:
        return "none"
    item = values[-1]
    if isinstance(item, Mapping):
        return ":".join(
            str(item.get(key, ""))
            for key in ("time", "open", "high", "low", "close", "value")
        )
    return str(item)


def _base_revision(payload: Mapping[str, Any]) -> str:
    parts = [
        str(payload.get("signature") or ""),
        f"candles:{len(payload.get('candles') or [])}:{_last_point(payload.get('candles'))}",
        f"volume:{len(payload.get('volume') or [])}:{_last_point(payload.get('volume'))}",
    ]
    for item in payload.get("lines") or []:
        if isinstance(item, Mapping):
            parts.append(
                f"line:{item.get('role')}:{len(item.get('data') or [])}:{_last_point(item.get('data'))}"
            )
    for item in payload.get("histograms") or []:
        if isinstance(item, Mapping):
            parts.append(
                f"hist:{item.get('role')}:{len(item.get('data') or [])}:{_last_point(item.get('data'))}"
            )
    return "|".join(parts)


def _component_key(chart_id: str, revision: str) -> str:
    digest = hashlib.blake2s(
        f"{chart_id}\0{revision}".encode("utf-8"),
        digest_size=16,
    ).hexdigest()
    return f"pg-lightweight-base-update-{digest}"


def render_lightweight_base_update_v1(payload: Mapping[str, Any]) -> None:
    """Apply closed-bar/indicator payload to the existing chart without remounting it."""

    chart_id = str(payload.get("chart_id") or "")
    revision = _base_revision(payload)
    _base_update_component(
        key=_component_key(chart_id, revision),
        data={"payload": dict(payload), "revision": revision},
        height=0,
    )


__all__ = [
    "_base_revision",
    "_component_key",
    "render_lightweight_base_update_v1",
]
