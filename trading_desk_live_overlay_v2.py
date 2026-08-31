from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

import streamlit as st

from saxo_chart_live import FormingCandle1m
from time_display_v2 import oslo_chart_time


_OVERLAY_JS = r"""
export default function(component) {
    const { data, parentElement, setStateValue } = component;
    const registry = window.__pricegaugerLiveCandleOverlays ||= new Map();
    const registryKey = String(data.uirevision);
    const entry = registry.get(registryKey) || { candles: new Map() };
    registry.set(registryKey, entry);

    if (data.active && data.candle) {
        const candleKey = String(data.candle.bar_time);
        const previous = entry.candles.get(candleKey);
        entry.candles.set(candleKey, previous ? {
            ...data.candle,
            open: Number(previous.open),
            high: Math.max(Number(previous.high), Number(data.candle.high)),
            low: Math.min(Number(previous.low), Number(data.candle.low)),
        } : data.candle);
        const ordered = Array.from(entry.candles.keys()).sort();
        for (const key of ordered.slice(0, Math.max(0, ordered.length - 240))) {
            entry.candles.delete(key);
        }
    } else {
        entry.candles.clear();
    }

    const canvasId = `pg-live-candle-${data.canvas_id}`;
    let graph = null;
    let canvas = null;
    let observer = null;

    function findGraph() {
        return Array.from(document.querySelectorAll('.js-plotly-plot')).find(
            (candidate) => String(candidate?.layout?.uirevision || '') === registryKey
        ) || null;
    }

    function ensureCanvas() {
        graph = findGraph();
        if (!graph || !graph._fullLayout) return false;
        canvas = graph.querySelector(`#${CSS.escape(canvasId)}`);
        if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.id = canvasId;
            canvas.setAttribute('aria-hidden', 'true');
            Object.assign(canvas.style, {
                position: 'absolute',
                inset: '0',
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                zIndex: '4',
            });
            graph.style.position = 'relative';
            graph.appendChild(canvas);
        }
        return true;
    }

    function draw() {
        if (!ensureCanvas()) return;
        const layout = graph._fullLayout;
        const xaxis = layout.xaxis;
        const yaxis = layout.yaxis;
        const size = layout._size;
        if (!xaxis || !yaxis || !size) return;

        const ratio = window.devicePixelRatio || 1;
        const bounds = graph.getBoundingClientRect();
        canvas.width = Math.max(1, Math.round(bounds.width * ratio));
        canvas.height = Math.max(1, Math.round(bounds.height * ratio));
        const context = canvas.getContext('2d');
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
        context.clearRect(0, 0, bounds.width, bounds.height);
        context.save();
        context.beginPath();
        context.rect(size.l, size.t, size.w, size.h);
        context.clip();

        for (const candle of entry.candles.values()) {
            const centerValue = xaxis.d2c(String(candle.bar_time));
            const centerX = size.l + xaxis.c2p(centerValue);
            const nextX = size.l + xaxis.c2p(centerValue + Number(data.timeframe_minutes) * 60000);
            const bodyWidth = Math.max(3, Math.min(26, Math.abs(nextX - centerX) * 0.62));
            const priceTrace = Array.from(graph.data || []).find((trace) => trace.type === 'candlestick');
            let baseIndex = -1;
            if (priceTrace) {
                baseIndex = Array.from(priceTrace.x || []).findIndex(
                    (value) => Math.abs(xaxis.d2c(value) - centerValue) < 1
                );
            }
            const open = baseIndex >= 0 ? Number(priceTrace.open[baseIndex]) : Number(candle.open);
            const high = Math.max(
                baseIndex >= 0 ? Number(priceTrace.high[baseIndex]) : Number(candle.high),
                Number(candle.high)
            );
            const low = Math.min(
                baseIndex >= 0 ? Number(priceTrace.low[baseIndex]) : Number(candle.low),
                Number(candle.low)
            );
            const close = Number(candle.close);
            const highY = size.t + yaxis.d2p(high);
            const lowY = size.t + yaxis.d2p(low);
            const openY = size.t + yaxis.d2p(open);
            const closeY = size.t + yaxis.d2p(close);
            const rising = close >= open;
            const color = rising ? '#0f9d58' : '#dc2626';

            context.strokeStyle = color;
            context.fillStyle = color;
            context.lineWidth = 1.4;
            context.beginPath();
            context.moveTo(centerX, highY);
            context.lineTo(centerX, lowY);
            context.stroke();
            const top = Math.min(openY, closeY);
            const height = Math.max(1.5, Math.abs(closeY - openY));
            context.fillRect(centerX - bodyWidth / 2, top, bodyWidth, height);
        }
        context.restore();
    }

    function currentView() {
        if (!graph?._fullLayout) return null;
        const xRange = graph._fullLayout.xaxis?.range;
        const yRange = graph._fullLayout.yaxis?.range;
        if (!Array.isArray(xRange) || !Array.isArray(yRange)) return null;
        return {
            x_range: xRange.map((value) => value instanceof Date ? value.toISOString() : String(value)),
            y_range: yRange.map(Number),
        };
    }

    function attach() {
        if (!ensureCanvas()) return false;
        draw();
        const onRelayout = () => {
            window.requestAnimationFrame(() => {
                draw();
                const view = currentView();
                if (view) setStateValue('view', view);
            });
        };
        const onDoubleClick = () => setStateValue('view', null);
        graph.on('plotly_relayout', onRelayout);
        graph.on('plotly_doubleclick', onDoubleClick);
        window.addEventListener('resize', draw);
        entry.cleanup?.();
        entry.cleanup = () => {
            graph?.removeListener?.('plotly_relayout', onRelayout);
            graph?.removeListener?.('plotly_doubleclick', onDoubleClick);
            window.removeEventListener('resize', draw);
        };
        return true;
    }

    if (!attach()) {
        observer = new MutationObserver(() => {
            if (attach()) observer.disconnect();
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    parentElement.style.display = 'none';
    return () => observer?.disconnect();
}
"""


_live_candle_overlay = st.components.v2.component(
    "pricegauger_live_candle_overlay_v2",
    js=_OVERLAY_JS,
    isolate_styles=False,
)


@dataclass(frozen=True, slots=True)
class LiveChartViewV2:
    x_range: tuple[str, str]
    y_range: tuple[float, float]


def live_chart_overlay_key_v2(uirevision: str) -> str:
    return f"pg-live-candle-overlay:{uirevision}"


def parse_live_chart_view_v2(value: Any) -> LiveChartViewV2 | None:
    if not isinstance(value, Mapping):
        return None
    raw = value.get("view", value)
    if not isinstance(raw, Mapping):
        return None
    x_range = raw.get("x_range")
    y_range = raw.get("y_range")
    if not isinstance(x_range, (list, tuple)) or len(x_range) != 2:
        return None
    if not isinstance(y_range, (list, tuple)) or len(y_range) != 2:
        return None
    try:
        y_values = (float(y_range[0]), float(y_range[1]))
    except (TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in y_values) or y_values[0] == y_values[1]:
        return None
    x_values = (str(x_range[0]), str(x_range[1]))
    if not all(item and len(item) <= 64 for item in x_values) or x_values[0] == x_values[1]:
        return None
    return LiveChartViewV2(x_range=x_values, y_range=y_values)


def forming_candle_payload_v2(
    candle: FormingCandle1m,
    *,
    timeframe_minutes: int = 1,
) -> dict[str, float | str]:
    minutes = int(timeframe_minutes)
    if minutes <= 0 or 60 % minutes != 0:
        raise ValueError("timeframe_minutes must be a positive divisor of 60")
    localized = oslo_chart_time(candle.bar_time)
    bucket = localized.replace(minute=(localized.minute // minutes) * minutes, second=0, microsecond=0)
    return {
        "bar_time": bucket.isoformat(),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
    }


def render_live_candle_overlay_v2(
    *,
    uirevision: str,
    timeframe_minutes: int,
    candle: FormingCandle1m | None,
) -> None:
    key = live_chart_overlay_key_v2(uirevision)
    canvas_id = str(abs(hash(uirevision)))
    _live_candle_overlay(
        key=key,
        data={
            "uirevision": uirevision,
            "canvas_id": canvas_id,
            "timeframe_minutes": int(timeframe_minutes),
            "active": candle is not None,
            "candle": forming_candle_payload_v2(candle, timeframe_minutes=timeframe_minutes) if candle is not None else None,
        },
        default={"view": None},
        on_view_change=lambda: None,
        height=0,
    )


__all__ = [
    "LiveChartViewV2",
    "forming_candle_payload_v2",
    "live_chart_overlay_key_v2",
    "parse_live_chart_view_v2",
    "render_live_candle_overlay_v2",
]
