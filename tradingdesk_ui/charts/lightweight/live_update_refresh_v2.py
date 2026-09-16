from __future__ import annotations

from typing import Sequence

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from saxo_chart_live import FormingCandle1m
from . import live_update as _legacy


def _revision(candle_payload, marker_payload) -> str:
    if candle_payload is None:
        candle = "none"
    else:
        candle = ":".join(str(candle_payload.get(key)) for key in ("time", "open", "high", "low", "close"))
    markers = "|".join(str(item.get("id", "")) for item in marker_payload)
    return f"{candle}:{markers}"


def render_lightweight_live_update_refresh_v2(
    *,
    chart_id: str,
    timeframe_minutes: int,
    candle: FormingCandle1m | None,
    trade_markers: Sequence[AutoTraderTradeMarkerV1] = (),
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
        key=f"pg-lightweight-live-update:{chart_id}:{revision}",
        data={
            "chart_id": str(chart_id),
            "timeframe_seconds": minutes * 60,
            "active": candle is not None,
            "candle": candle_payload,
            "trade_markers": markers,
            "revision": revision,
        },
        height=0,
    )


__all__ = ["render_lightweight_live_update_refresh_v2"]
