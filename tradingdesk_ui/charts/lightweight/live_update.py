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

    function apply() {
        const entry = registry?.get?.(chartId) || null;
        if (!entry?.candles) return false;
        if (!(entry.formingCandles instanceof Map)) entry.formingCandles = new Map();

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
    """Update the direct Lightweight LIVE candle/markers without Streamlit navigation state."""

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
