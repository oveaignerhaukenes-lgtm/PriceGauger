from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from trading_desk import ChartBar, utc
from trading_desk_indicators import INDICATOR_SWING_BANDS, TechnicalIndicators
from trading_desk_swing_bands import derive_swing_bands
from tradingdesk_ui.charts.lightweight.contract import build_lightweight_live_payload_v1


def build_lightweight_direct_live_payload_v1(
    *,
    market: str,
    timeframe: str,
    primary: Sequence[ChartBar],
    overlays: Mapping[str, Sequence[ChartBar]],
    overlay_mode: str,
    indicators: TechnicalIndicators | None,
    indicator_names: Sequence[str],
    indicator_timeframes: Mapping[str, str],
    chart_height: int,
    price_panel_share: float,
    trade_markers: Sequence[AutoTraderTradeMarkerV1] = (),
) -> dict[str, Any]:
    """Extend the stable LWC contract with direct-render-only structural primitives."""

    payload = build_lightweight_live_payload_v1(
        market=market,
        timeframe=timeframe,
        primary=primary,
        overlays=overlays,
        overlay_mode=overlay_mode,
        indicators=indicators,
        indicator_names=indicator_names,
        indicator_timeframes=indicator_timeframes,
        chart_height=chart_height,
        price_panel_share=price_panel_share,
        trade_markers=trade_markers,
    )
    bands: list[dict[str, Any]] = []
    if INDICATOR_SWING_BANDS in set(str(item) for item in indicator_names) and primary:
        for band in derive_swing_bands(primary):
            bands.append(
                {
                    "kind": str(band.kind),
                    "pivot_price": float(band.pivot_price),
                    "lower": float(band.lower),
                    "upper": float(band.upper),
                    "pivot_time": int(utc(band.pivot_time).timestamp()),
                }
            )
    payload["swing_bands"] = bands
    payload["signature"] = f"{payload.get('signature', '')}|direct-v1|swing:{len(bands)}"
    return payload


__all__ = ["build_lightweight_direct_live_payload_v1"]
