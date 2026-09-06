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
                color: direction === 'LONG' ? '#16a34a' : '#dc2626',
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

        function refreshGeometry() {
            let paneHeight = 0;
            try { paneHeight = Number(entry.chart?.panes?.()?.[0]?.getHeight?.() || 0); } catch (_) {}
            if (!Number.isFinite(paneHeight) || paneHeight <= 0) paneHeight = Math.max(80, root.clientHeight * 0.5);
            layer.style.height = `${paneHeight}px`;
        }

        layer.addEventListener('pointerdown', (event) => {
            const priceScale = entry.candles?.priceScale?.();
            const range = priceScale?.getVisibleRange?.();
            if (!range || !Number.isFinite(Number(range.from)) || !Number.isFinite(Number(range.to))) return;
            event.preventDefault();
            event.stopPropagation();
            const paneHeight = Math.max(80, Number(entry.chart?.panes?.()?.[0]?.getHeight?.() || root.clientHeight || 320));
            drag = {
                pointerId: event.pointerId,
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
            if (quickTap && now - lastTapAt < 360) {
                try { drag.priceScale.setAutoScale(true); } catch (_) {}
                lastTapAt = 0;
            } else if (quickTap) {
                lastTapAt = now;
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

    function ensureBottomPaneResize(entry) {
        if (!entry?.root || entry.bottomPaneResizeBound) return;
        const root = entry.root;
        const handle = document.createElement('div');
        handle.className = 'pg-lightweight-bottom-pane-resize';
        Object.assign(handle.style, {
            position: 'absolute',
            left: '0',
            right: '82px',
            bottom: '26px',
            height: '18px',
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
            top: '8px',
            width: '38px',
            height: '2px',
            transform: 'translateX(-50%)',
            borderRadius: '999px',
            background: 'rgba(148,163,184,.45)',
            pointerEvents: 'none',
        });
        handle.appendChild(grip);
        root.appendChild(handle);

        let drag = null;

        function panes() {
            try { return Array.from(entry.chart?.panes?.() || []); } catch (_) { return []; }
        }

        function refreshGeometry() {
            const all = panes();
            handle.style.display = all.length > 1 ? 'block' : 'none';
            let timeHeight = 28;
            try { timeHeight = Number(entry.chart?.timeScale?.()?.height?.() || 28); } catch (_) {}
            handle.style.bottom = `${Math.max(0, timeHeight - 9)}px`;
        }

        handle.addEventListener('pointerdown', (event) => {
            const all = panes();
            const lastPane = all[all.length - 1];
            if (!lastPane?.getHeight || !lastPane?.setHeight) return;
            event.preventDefault();
            event.stopPropagation();
            drag = {
                pointerId: event.pointerId,
                startY: Number(event.clientY),
                startHeight: Number(lastPane.getHeight()),
                lastPane,
            };
            try { handle.setPointerCapture(event.pointerId); } catch (_) {}
        }, { passive: false });

        handle.addEventListener('pointermove', (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const dy = Number(event.clientY) - drag.startY;
            const maxHeight = Math.max(90, Number(root.clientHeight || 780) - 150);
            const nextHeight = Math.max(70, Math.min(maxHeight, drag.startHeight + dy));
            try { drag.lastPane.setHeight(nextHeight); } catch (_) {}
            entry.refreshTouchPriceAxisGeometry?.();
        }, { passive: false });

        const finishResize = (event) => {
            if (!drag || drag.pointerId !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            try { handle.releasePointerCapture(event.pointerId); } catch (_) {}
            drag = null;
            refreshGeometry();
        };
        handle.addEventListener('pointerup', finishResize, { passive: false });
        handle.addEventListener('pointercancel', finishResize, { passive: false });

        entry.bottomPaneResizeBound = true;
        entry.bottomPaneResizeHandle = handle;
        entry.refreshBottomPaneResizeGeometry = refreshGeometry;
        refreshGeometry();
    }

    function apply() {
        const entry = registry?.get?.(chartId) || null;
        if (!entry?.candles) return false;
        if (!(entry.formingCandles instanceof Map)) entry.formingCandles = new Map();
        ensureTouchPriceAxisDrag(entry);
        ensureBottomPaneResize(entry);
        entry.refreshTouchPriceAxisGeometry?.();
        entry.refreshBottomPaneResizeGeometry?.();

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
