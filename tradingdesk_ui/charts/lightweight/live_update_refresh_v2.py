from __future__ import annotations

import hashlib
from typing import Sequence

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from saxo_chart_live import FormingCandle1m
from . import live_update as _legacy
from .trade_marker_overlay_v2 import render_trade_marker_overlay_v2


def _revision(candle_payload, marker_payload) -> str:
    if candle_payload is None:
        candle = "none"
    else:
        candle = ":".join(str(candle_payload.get(key)) for key in ("time", "open", "high", "low", "close"))
    markers = "|".join(str(item.get("id", "")) for item in marker_payload)
    return f"{candle}:{markers}"


def _component_key(chart_id: str, revision: str) -> str:
    """Return a Streamlit bidi-safe key while preserving revision remount semantics.

    Streamlit components.v2 reserves ``__`` inside the computed bidi component ID.
    Canonical product/marker identifiers may legitimately contain that sequence
    (for example ``4912__CfdOnIndex``), so raw chart/revision data must never be
    embedded directly in the component key.  A deterministic hex digest keeps the
    key stable for one payload revision and changes it whenever chart/revision
    changes, without leaking reserved delimiters into the ID.
    """
    raw = f"{chart_id}\0{revision}".encode("utf-8")
    digest = hashlib.blake2s(raw, digest_size=16).hexdigest()
    return f"pg-lightweight-live-update-{digest}"


def render_lightweight_live_update_refresh_v2(
    *,
    chart_id: str,
    timeframe_minutes: int,
    candle: FormingCandle1m | None,
    trade_markers: Sequence[AutoTraderTradeMarkerV1] = (),
    refresh_ms: int = 0,
) -> None:
    """Compatibility wrapper for Streamlit v2 component fragment reruns.

    The old updater used one stable component key.  Recent Streamlit component-v2
    reconciliation can retain that keyed component across fragment reruns without
    re-running its JS.  A payload-derived key makes every changed forming candle a
    fresh zero-height updater mount while leaving the main chart itself untouched.
    """
    minutes = int(timeframe_minutes)
    candle_payload = _legacy._forming_payload(candle, timeframe_minutes=minutes) if candle is not None else None
    markers = _legacy._marker_payload(trade_markers)
    revision = _revision(candle_payload, markers)
    _legacy._live_update_component(
        key=_component_key(str(chart_id), revision),
        data={
            "chart_id": str(chart_id),
            "timeframe_seconds": minutes * 60,
            "active": candle is not None,
            "candle": candle_payload,
            "trade_markers": markers,
            "revision": revision,
            "refresh_ms": max(0, int(refresh_ms)),
        },
        height=0,
        on_live_tick_change=lambda: None,
    )
    # Reapply the complete marker set after the legacy updater.  LONG/SHORT keep
    # their arrows; confirmed FLAT transitions are neutral squares.
    render_trade_marker_overlay_v2(
        chart_id=str(chart_id),
        timeframe_seconds=minutes * 60,
        trade_markers=markers,
        revision=revision,
    )


__all__ = ["_component_key", "render_lightweight_live_update_refresh_v2"]
