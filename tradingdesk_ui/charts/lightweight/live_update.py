from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import streamlit as st

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from saxo_chart_live import FormingCandle1m


_LIGHTWEIGHT_LIVE_UPDATE_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const chartId = String(data.chart_id || '');
    const registry = window.__pricegaugerLightweightCharts;
    const geometryKey = `pg:tradingdesk:lightweight-geometry:v1:${chartId}`;
    let retryTimer = null;

    function cleanNumber(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    }

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

    function markerPayload(entry) {
        const times = Array.from(entry?.baseCandles?.keys?.() || [])
            .map(Number).filter(Number.isFinite).sort((a, b) => a - b);
        if (!times.length) return [];
        const grace = Math.max(60, Number(data.timeframe_seconds || 60));
        const first = times[0];
        const last = times[times.length - 1];
        return Array.from(data.trade_markers || []).flatMap((marker, index) => {
            const raw = Number(marker.executed_at);
            const price = cleanNumber(marker.execution_price);
            if (!Number.isFinite(raw) || price == null || raw < first - grace || raw > last + grace) return [];
            const time = nearestTime(times, raw);
            if (time == null) return [];
            const direction = String(marker.direction || '').toUpperCase();
            if (direction !== 'LONG' && direction !== 'SHORT') return [];
            return [{
                time,
                price,
                position: 'atPriceMiddle',
                shape: direction === 'LONG' ? 'arrowUp' : 'arrowDown',
                color: direction === 'LONG' ? '#0ea5e9' : '#f59e0b',
                size: marker.active ? 1.0 : 0.72,
                id: `${marker.id || raw}:${index}`,
            }];
        });
    }

    function restoreBase(entry) {
        if (!entry?.formingCandles?.size) return;
        for (const [time] of entry.formingCandles.entries()) {
            const base = entry.baseCandles?.get?.(Number(time));
            if (base) {
                try { entry.candles.update(base); } catch (_) {}
            }
        }
        entry.formingCandles.clear();
    }

    function panes(entry) {
        try { return Array.from(entry.chart?.panes?.() || []); } catch (_) { return []; }
    }

    function paneRatios(entry) {
        const all = panes(entry);
        const heights = all.map((pane) => Math.max(0, Number(pane?.getHeight?.() || 0)));
        const total = heights.reduce((sum, value) => sum + value, 0);
        if (!total) return [];
        return heights.map((value) => value / total);
    }

    function readGeometry() {
        try {
            const raw = window.localStorage?.getItem(geometryKey);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : null;
        } catch (_) {
            return null;
        }
    }

    function writeGeometry(entry, forcedHeight = null, forcedRatios = null) {
        const height = forcedHeight == null
            ? Math.round(Number(entry.parent?.getBoundingClientRect?.().height || entry.root?.clientHeight || 0))
            : Math.round(Number(forcedHeight));
        const ratios = Array.isArray(forcedRatios) ? forcedRatios : paneRatios(entry);
        if (!Number.isFinite(height) || height < 240 || !ratios.length) return;
        try {
            window.localStorage?.setItem(geometryKey, JSON.stringify({ height, pane_ratios: ratios }));
        } catch (_) {}
    }

    function applyPaneRatios(entry, ratios) {
        const all = panes(entry);
        if (!Array.isArray(ratios) || ratios.length !== all.length || !all.length) return;
        const total = all.reduce((sum, pane) => sum + Math.max(0, Number(pane?.getHeight?.() || 0)), 0);
        if (!total) return;
        for (let index = 0; index < all.length; index += 1) {
            const ratio = Math.max(0.04, Number(ratios[index] || 0));
            try { all[index]?.setHeight?.(Math.max(52, total * ratio)); } catch (_) {}
        }
    }

    function hydrateGeometry(entry) {
        const saved = readGeometry();
        if (!saved) return;
        const height = Math.max(320, Math.min(1400, Number(saved.height || 0)));
        if (Number.isFinite(height) && height > 0) {
            entry.parent.style.height = `${height}px`;
            entry.root.style.height = '100%';
        }
        if (!entry.geometryHydrated) {
            entry.geometryHydrated = true;
            window.requestAnimationFrame(() => applyPaneRatios(entry, saved.pane_ratios));
        }
    }

    function scaleSeriesForPanes(entry) {
        const result = [entry.candles];
        const groups = [
            ['macd', 'macd_signal', 'macd_histogram'],
            ['rsi'],
            ['stochastic_k', 'stochastic_d'],
            ['atr'],
        ];
        for (const group of groups) {
            const candidate = group.map((role) => entry.series?.get?.(role)).find(Boolean);
            if (candidate) result.push(candidate);
        }
        return result;
    }

    function paneIndexAtY(entry, clientY) {
        const rootRect = entry.root.getBoundingClientRect();
        const y = Number(clientY) - rootRect.top;
        const all = panes(entry);
        let cursor = 0;
        for (let index = 0; index < all.length; index += 1) {
            const height = Math.max(0, Number(all[index]?.getHeight?.() || 0));
            if (y >= cursor && y <= cursor + height) return index;
            cursor += height;
        }
        return -1;
    }

    function ensureTouchPriceAxisDrag(entry) {
        if (!entry?.root || entry.touchPriceAxisDragBound) return;
        if (!Number(navigator.maxTouchPoints || 0)) {
            entry.touchPriceAxisDragBound = true;
            return;
        }

        const root = entry.root;
        const layer = document.createElement('div');
        layer.className = 'pg-lightweight-touch-price-axis';
        Object.assign(layer.style, {
            position: 'absolute',
            right: '0',
            top: '0',
            width: '82px',
            height: '0px',
            zIndex: '9',
            background: 'transparent',
            touchAction: 'none',
            cursor: 'ns-resize',
            userSelect: 'none',
            WebkitUserSelect: 'none',
        });
        root.appendChild(layer);

        let drag = null;
        let lastTapAt = 0;
        let lastTapPane = -1;

        function refreshGeometry() {
            const totalPaneHeight = panes(entry).reduce(
                (sum, pane) => sum + Math.max(0, Number(pane?.getHeight?.() || 0)),
                0,
            );
            layer.style.height = `${Math.max(80, totalPaneHeight)}px`;
        }

        layer.addEventListener('pointerdown', (event) => {
            const paneIndex = paneIndexAtY(entry, event.clientY);
            const series = scaleSeriesForPanes(entry)[paneIndex];
            const priceScale = series?.priceScale?.();
            const range = priceScale?.getVisibleRange?.();
            if (!range || !Number.isFinite(Number(range.from)) || !Number.isFinite(Number(range.to))) return;
            event.preventDefault();
            event.stopPropagation();
            const paneHeight = Math.max(70, Number(panes(entry)[paneIndex]?.getHeight?.() || 120));
            drag = {
                pointerId: event.pointerId,
                paneIndex,
                startY: Number(event.clientY),
                startFrom: Number(range.from),
                startTo: Number(range.to),
                paneHeight,
                moved: false,
                startedAt: performance.now(),
                priceScale,
            };
            try { priceScale.setAutoScale(false); } catch (_) {}
            try { layer.setPointerCapture(event.pointerId); } catch (_) {}
        }, { passive: false });

        layer.addEventListener('pointermove', (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const dy = Number(event.clientY) - drag.startY;
            if (Math.abs(dy) > 3) drag.moved = true;
            const center = (drag.startFrom + drag.startTo) / 2;
            const halfSpan = Math.max(1e-9, (drag.startTo - drag.startFrom) / 2);
            const factor = Math.exp((dy / drag.paneHeight) * 2.2);
            const nextHalf = halfSpan * Math.max(0.08, Math.min(12, factor));
            try {
                drag.priceScale.setVisibleRange({ from: center - nextHalf, to: center + nextHalf });
            } catch (_) {}
        }, { passive: false });

        const finishDrag = (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const now = performance.now();
            const quickTap = !drag.moved && now - drag.startedAt < 260;
            if (quickTap && lastTapPane === drag.paneIndex && now - lastTapAt < 360) {
                try { drag.priceScale.setAutoScale(true); } catch (_) {}
                lastTapAt = 0;
                lastTapPane = -1;
            } else if (quickTap) {
                lastTapAt = now;
                lastTapPane = drag.paneIndex;
            }
            try { layer.releasePointerCapture(event.pointerId); } catch (_) {}
            drag = null;
        };
        layer.addEventListener('pointerup', finishDrag, { passive: false });
        layer.addEventListener('pointercancel', finishDrag, { passive: false });

        entry.touchPriceAxisDragBound = true;
        entry.touchPriceAxisDragLayer = layer;
        entry.refreshTouchPriceAxisGeometry = refreshGeometry;
        refreshGeometry();
    }

    function ensureTouchTimeAxisScale(entry) {
        if (!entry?.root || entry.touchTimeAxisScaleBound) return;
        if (!Number(navigator.maxTouchPoints || 0)) {
            entry.touchTimeAxisScaleBound = true;
            return;
        }

        const root = entry.root;
        const layer = document.createElement('div');
        layer.className = 'pg-lightweight-touch-time-axis';
        Object.assign(layer.style, {
            position: 'absolute',
            left: '0',
            right: '82px',
            bottom: '0',
            height: '34px',
            zIndex: '9',
            background: 'transparent',
            touchAction: 'none',
            cursor: 'ew-resize',
            userSelect: 'none',
            WebkitUserSelect: 'none',
        });
        root.appendChild(layer);

        let drag = null;
        let lastTapAt = 0;

        layer.addEventListener('pointerdown', (event) => {
            const timeScale = entry.chart?.timeScale?.();
            const range = timeScale?.getVisibleLogicalRange?.();
            if (!range || !Number.isFinite(Number(range.from)) || !Number.isFinite(Number(range.to))) return;
            event.preventDefault();
            event.stopPropagation();
            drag = {
                pointerId: event.pointerId,
                startX: Number(event.clientX),
                startFrom: Number(range.from),
                startTo: Number(range.to),
                width: Math.max(120, Number(layer.getBoundingClientRect().width || root.clientWidth || 320)),
                moved: false,
                startedAt: performance.now(),
                timeScale,
            };
            try { layer.setPointerCapture(event.pointerId); } catch (_) {}
        }, { passive: false });

        layer.addEventListener('pointermove', (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const dx = Number(event.clientX) - drag.startX;
            if (Math.abs(dx) > 3) drag.moved = true;
            const center = (drag.startFrom + drag.startTo) / 2;
            const halfSpan = Math.max(0.5, (drag.startTo - drag.startFrom) / 2);
            const factor = Math.exp((dx / drag.width) * 2.4);
            const nextHalf = halfSpan * Math.max(0.08, Math.min(12, factor));
            try {
                drag.timeScale.setVisibleLogicalRange({ from: center - nextHalf, to: center + nextHalf });
            } catch (_) {}
        }, { passive: false });

        const finishDrag = (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const now = performance.now();
            const quickTap = !drag.moved && now - drag.startedAt < 260;
            if (quickTap && now - lastTapAt < 360) {
                try { drag.timeScale.fitContent(); } catch (_) {}
                lastTapAt = 0;
            } else if (quickTap) {
                lastTapAt = now;
            }
            try { layer.releasePointerCapture(event.pointerId); } catch (_) {}
            drag = null;
        };
        layer.addEventListener('pointerup', finishDrag, { passive: false });
        layer.addEventListener('pointercancel', finishDrag, { passive: false });

        entry.touchTimeAxisScaleBound = true;
        entry.touchTimeAxisScaleLayer = layer;
    }

    function ensureChartHeightResize(entry) {
        if (!entry?.root || entry.chartHeightResizeBound) return;
        const root = entry.root;
        const handle = document.createElement('div');
        handle.className = 'pg-lightweight-chart-height-resize';
        Object.assign(handle.style, {
            position: 'absolute',
            left: '50%',
            bottom: '34px',
            width: '128px',
            height: '18px',
            transform: 'translateX(-50%)',
            zIndex: '10',
            touchAction: 'none',
            cursor: 'ns-resize',
            userSelect: 'none',
            WebkitUserSelect: 'none',
            background: 'transparent',
        });

        const grip = document.createElement('div');
        Object.assign(grip.style, {
            position: 'absolute',
            left: '50%',
            bottom: '3px',
            width: '46px',
            height: '3px',
            transform: 'translateX(-50%)',
            borderRadius: '999px',
            background: 'rgba(148,163,184,.58)',
            pointerEvents: 'none',
        });
        handle.appendChild(grip);
        root.appendChild(handle);

        let drag = null;

        handle.addEventListener('pointerdown', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const currentHeight = Math.max(320, Number(entry.parent?.getBoundingClientRect?.().height || root.clientHeight || 780));
            drag = {
                pointerId: event.pointerId,
                startY: Number(event.clientY),
                startHeight: currentHeight,
                ratios: paneRatios(entry),
            };
            try { handle.setPointerCapture(event.pointerId); } catch (_) {}
        }, { passive: false });

        handle.addEventListener('pointermove', (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const dy = Number(event.clientY) - drag.startY;
            const nextHeight = Math.max(320, Math.min(1400, drag.startHeight + dy));
            entry.parent.style.height = `${nextHeight}px`;
            entry.root.style.height = '100%';
            window.requestAnimationFrame(() => {
                applyPaneRatios(entry, drag?.ratios || []);
                entry.refreshTouchPriceAxisGeometry?.();
            });
        }, { passive: false });

        const finishResize = (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const finalHeight = Math.max(320, Number(entry.parent?.getBoundingClientRect?.().height || root.clientHeight || drag.startHeight));
            writeGeometry(entry, finalHeight, drag.ratios);
            try { handle.releasePointerCapture(event.pointerId); } catch (_) {}
            drag = null;
            entry.refreshTouchPriceAxisGeometry?.();
        };
        handle.addEventListener('pointerup', finishResize, { passive: false });
        handle.addEventListener('pointercancel', finishResize, { passive: false });

        // Native pane-separator drags update the relative layout. Persist those ratios
        // after any ordinary pointer gesture without affecting navigation state.
        root.addEventListener('pointerup', (event) => {
            if (!handle.contains(event.target)) writeGeometry(entry);
        }, { passive: true });

        entry.chartHeightResizeBound = true;
        entry.chartHeightResizeHandle = handle;
    }

    function apply() {
        const entry = registry?.get?.(chartId) || null;
        if (!entry?.candles) return false;
        if (!(entry.formingCandles instanceof Map)) entry.formingCandles = new Map();
        hydrateGeometry(entry);
        ensureTouchPriceAxisDrag(entry);
        ensureTouchTimeAxisScale(entry);
        ensureChartHeightResize(entry);
        entry.refreshTouchPriceAxisGeometry?.();

        if (data.active && data.candle) {
            const incoming = data.candle;
            const time = Number(incoming.time);
            const open = cleanNumber(incoming.open);
            const high = cleanNumber(incoming.high);
            const low = cleanNumber(incoming.low);
            const close = cleanNumber(incoming.close);
            if (Number.isFinite(time) && [open, high, low, close].every((value) => value != null)) {
                const base = entry.baseCandles?.get?.(time) || null;
                const previous = entry.formingCandles.get(time) || null;
                const merged = {
                    time,
                    open: base ? Number(base.open) : previous ? Number(previous.open) : open,
                    high: Math.max(high, base ? Number(base.high) : high, previous ? Number(previous.high) : high),
                    low: Math.min(low, base ? Number(base.low) : low, previous ? Number(previous.low) : low),
                    close,
                };
                entry.formingCandles.set(time, merged);
                for (const staleTime of Array.from(entry.formingCandles.keys())) {
                    if (Number(staleTime) !== time) entry.formingCandles.delete(staleTime);
                }
                try { entry.candles.update(merged); } catch (_) {}
            }
        } else {
            restoreBase(entry);
        }

        try { entry.markers?.setMarkers?.(markerPayload(entry)); } catch (_) {}
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


_live_update_component = st.components.v2.component(
    "pricegauger_tradingdesk_lightweight_live_update_v1",
    js=_LIGHTWEIGHT_LIVE_UPDATE_JS,
    isolate_styles=False,
)


def _epoch_seconds(value: object) -> int:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _forming_payload(candle: FormingCandle1m, *, timeframe_minutes: int) -> dict[str, float | int]:
    minutes = int(timeframe_minutes)
    if minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    seconds = minutes * 60
    raw_time = _epoch_seconds(candle.bar_time)
    bucket_time = raw_time - (raw_time % seconds)
    return {
        "time": bucket_time,
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
    }


def _marker_payload(markers: Sequence[AutoTraderTradeMarkerV1]) -> list[dict[str, Any]]:
    return [
        {
            "executed_at": _epoch_seconds(marker.executed_at),
            "execution_price": float(marker.execution_price),
            "direction": str(marker.direction),
            "active": bool(marker.active),
            "id": f"{marker.net_position_id}:{_epoch_seconds(marker.executed_at)}",
        }
        for marker in markers
    ]


def render_lightweight_live_update_v1(
    *,
    chart_id: str,
    timeframe_minutes: int,
    candle: FormingCandle1m | None,
    trade_markers: Sequence[AutoTraderTradeMarkerV1] = (),
) -> None:
    """Update direct Lightweight LIVE state plus touch-only chart interaction helpers."""

    minutes = int(timeframe_minutes)
    _live_update_component(
        key=f"pg-lightweight-live-update:{chart_id}",
        data={
            "chart_id": str(chart_id),
            "timeframe_seconds": minutes * 60,
            "active": candle is not None,
            "candle": _forming_payload(candle, timeframe_minutes=minutes) if candle is not None else None,
            "trade_markers": _marker_payload(trade_markers),
        },
        height=0,
    )


__all__ = ["render_lightweight_live_update_v1"]
