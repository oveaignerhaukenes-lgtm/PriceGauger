from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

import streamlit as st

from autotrader_strategy_catalog_v2 import strategy_display_label_v2
from autotrader_trade_markers_v1 import load_autotrader_trade_markers_v1
from saxo_chart_live import FormingCandle1m
from time_display_v2 import oslo_chart_time


_OVERLAY_JS = r"""
export default function(component) {
    const { data, parentElement, setStateValue } = component;
    const registry = window.__pricegaugerLiveCandleOverlays ||= new Map();
    const registryKey = String(data.uirevision);
    const entry = registry.get(registryKey) || { candles: new Map(), tradeMarkers: [] };
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
    entry.tradeMarkers = Array.isArray(data.trade_markers) ? data.trade_markers : [];

    const canvasId = `pg-live-candle-${data.canvas_id}`;
    let graph = null;
    let canvas = null;
    let observer = null;
    let persistTimer = null;

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

    function drawTradeMarker(context, xaxis, yaxis, size, marker) {
        const price = Number(marker.execution_price);
        if (!Number.isFinite(price)) return;
        const xValue = xaxis.d2c(String(marker.executed_at));
        const x = size.l + xaxis.c2p(xValue);
        const y = size.t + yaxis.d2p(price);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        if (x < size.l - 24 || x > size.l + size.w + 24 || y < size.t - 24 || y > size.t + size.h + 24) return;

        const direction = String(marker.direction || '').toUpperCase();
        const active = Boolean(marker.active);
        const radius = active ? 11 : 7;
        const color = direction === 'LONG' ? '#16a34a' : '#dc2626';
        const upward = direction === 'LONG';

        context.save();
        context.globalAlpha = active ? 1.0 : 0.88;
        context.beginPath();
        if (upward) {
            context.moveTo(x, y - radius);
            context.lineTo(x - radius * 0.9, y + radius * 0.72);
            context.lineTo(x + radius * 0.9, y + radius * 0.72);
        } else {
            context.moveTo(x, y + radius);
            context.lineTo(x - radius * 0.9, y - radius * 0.72);
            context.lineTo(x + radius * 0.9, y - radius * 0.72);
        }
        context.closePath();
        context.fillStyle = color;
        context.fill();
        context.lineWidth = active ? 2.2 : 1.1;
        context.strokeStyle = active ? '#111827' : 'rgba(17,24,39,0.58)';
        context.stroke();

        if (active) {
            context.globalAlpha = 1.0;
            context.font = '600 11px system-ui, -apple-system, sans-serif';
            context.textAlign = 'center';
            context.textBaseline = upward ? 'bottom' : 'top';
            context.fillStyle = color;
            context.fillText(`AKTIV ${direction}`, x, y + (upward ? -radius - 4 : radius + 4));
        }
        context.restore();
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
            const bodyWidth = Math.max(3, Math.min(7, Math.abs(nextX - centerX) * 0.38));
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
            context.lineWidth = 1.0;
            context.beginPath();
            context.moveTo(centerX, highY);
            context.lineTo(centerX, lowY);
            context.stroke();
            const top = Math.min(openY, closeY);
            const height = Math.max(1.25, Math.abs(closeY - openY));
            context.fillRect(centerX - bodyWidth / 2, top, bodyWidth, height);
        }

        for (const marker of entry.tradeMarkers) {
            drawTradeMarker(context, xaxis, yaxis, size, marker);
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

    function persistViewSoon() {
        if (persistTimer) window.clearTimeout(persistTimer);
        persistTimer = window.setTimeout(() => {
            persistTimer = null;
            const view = currentView();
            if (view) setStateValue('view', view);
        }, 180);
    }

    function attach() {
        if (!ensureCanvas()) return false;
        draw();
        const onRelayout = () => {
            window.requestAnimationFrame(draw);
            persistViewSoon();
        };
        const onDoubleClick = () => {
            if (persistTimer) window.clearTimeout(persistTimer);
            persistTimer = null;
            setStateValue('view', null);
        };
        graph.on('plotly_relayout', onRelayout);
        graph.on('plotly_doubleclick', onDoubleClick);
        window.addEventListener('resize', draw);
        entry.cleanup?.();
        entry.cleanup = () => {
            graph?.removeListener?.('plotly_relayout', onRelayout);
            graph?.removeListener?.('plotly_doubleclick', onDoubleClick);
            window.removeEventListener('resize', draw);
            if (persistTimer) window.clearTimeout(persistTimer);
            persistTimer = null;
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


def _market_from_uirevision_v1(uirevision: str) -> str | None:
    value = str(uirevision or "")
    if not value.startswith("TradingDesk:"):
        return None
    parts = value.split(":")
    if len(parts) < 4:
        return None
    market = parts[1].strip()
    return market or None


@st.cache_data(ttl=3, show_spinner=False)
def _trade_marker_payload_for_market_v1(market_name: str) -> tuple[dict[str, Any], ...]:
    markers = load_autotrader_trade_markers_v1(market_name)
    return tuple(
        {
            "executed_at": oslo_chart_time(marker.executed_at).isoformat(),
            "execution_price": float(marker.execution_price),
            "direction": marker.direction,
            "amount": float(marker.amount),
            "strategy": strategy_display_label_v2(marker.strategy_key),
            "active": bool(marker.active),
            "source": marker.source,
        }
        for marker in markers
    )


def render_live_candle_overlay_v2(
    *,
    uirevision: str,
    timeframe_minutes: int,
    candle: FormingCandle1m | None,
) -> None:
    key = live_chart_overlay_key_v2(uirevision)
    canvas_id = str(abs(hash(uirevision)))
    market_name = _market_from_uirevision_v1(uirevision)
    trade_markers = () if market_name is None else _trade_marker_payload_for_market_v1(market_name)
    _live_candle_overlay(
        key=key,
        data={
            "uirevision": uirevision,
            "canvas_id": canvas_id,
            "timeframe_minutes": int(timeframe_minutes),
            "active": candle is not None,
            "candle": forming_candle_payload_v2(candle, timeframe_minutes=timeframe_minutes) if candle is not None else None,
            "trade_markers": trade_markers,
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
