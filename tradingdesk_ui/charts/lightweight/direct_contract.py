from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from trading_desk import ChartBar, utc
from trading_desk_indicators import INDICATOR_SWING_BANDS, TechnicalIndicators
from trading_desk_swing_bands import derive_swing_bands
from tradingdesk_ui.charts.lightweight.contract import build_lightweight_live_payload_v1
from tradingdesk_ui.charts.lightweight.rollover_markers import load_rollover_marker_events_v1


# First successful production activation of PR #344 on the stream/runtime service.
# This is presentation-only provenance so later Strategy Lab/chart inspection has a
# visible boundary between the former closed-bar simple MACD controls and the shared
# restart-safe intrabar 1m/2m/5m/15m execution clock.
MACD_INTRABAR_ROLLOUT_AT_V1 = datetime(2026, 9, 8, 9, 32, 58, 272000, tzinfo=timezone.utc)
MACD_INTRABAR_ROLLOUT_LABEL_V1 = "MACD LIVE · 1/2/5/15m"


def _marker_bar_at_or_after(
    primary: Sequence[ChartBar],
    occurred_at: datetime,
) -> ChartBar | None:
    return next((bar for bar in primary if utc(bar.bar_time) >= utc(occurred_at)), None)


def _macd_rollout_chart_markers(primary: Sequence[ChartBar]) -> list[dict[str, Any]]:
    if not primary:
        return []
    first = utc(primary[0].bar_time)
    last = utc(primary[-1].bar_time)
    if MACD_INTRABAR_ROLLOUT_AT_V1 < first or MACD_INTRABAR_ROLLOUT_AT_V1 > last:
        return []
    marker_bar = _marker_bar_at_or_after(primary, MACD_INTRABAR_ROLLOUT_AT_V1)
    if marker_bar is None:
        return []
    return [
        {
            "time": int(utc(marker_bar.bar_time).timestamp()),
            "position": "aboveBar",
            "color": "#8b5cf6",
            "shape": "square",
            "text": MACD_INTRABAR_ROLLOUT_LABEL_V1,
            "size": 1.5,
        }
    ]


def _rollover_chart_markers(
    primary: Sequence[ChartBar],
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not primary or not events:
        return []
    result: list[dict[str, Any]] = []
    for event in events:
        raw_at = event.get("occurred_at")
        if isinstance(raw_at, datetime):
            occurred_at = utc(raw_at)
        else:
            try:
                occurred_at = utc(datetime.fromisoformat(str(raw_at).replace("Z", "+00:00")))
            except Exception:
                continue
        marker_bar = _marker_bar_at_or_after(primary, occurred_at)
        if marker_bar is None:
            # A rollover can be resolved while the exchange is closed. Do not pin it
            # to the old contract's last bar; it will appear on the first new-contract
            # bar after the market reopens.
            continue
        old_symbol = str(event.get("old_symbol") or event.get("old_uic") or "gammel")
        new_symbol = str(event.get("new_symbol") or event.get("new_uic") or "ny")
        result.append(
            {
                "time": int(utc(marker_bar.bar_time).timestamp()),
                "position": "aboveBar",
                "color": "#dc2626",
                "shape": "square",
                "text": f"ROLLOVER · {old_symbol} → {new_symbol}",
                "size": 2,
            }
        )
    return result


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
    rollover_events: Sequence[Mapping[str, Any]] | None = None,
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

    resolved_rollovers: Sequence[Mapping[str, Any]] = rollover_events or ()
    if rollover_events is None:
        try:
            resolved_rollovers = load_rollover_marker_events_v1(market=market)
        except Exception:
            # Presentation must stay available while a deployment/schema migration is
            # in flight. Missing marker history never changes market data or execution.
            resolved_rollovers = ()
    rollover_markers = _rollover_chart_markers(primary, resolved_rollovers)
    macd_rollout_markers = _macd_rollout_chart_markers(primary)
    payload["markers"] = [
        *list(payload.get("markers") or []),
        *rollover_markers,
        *macd_rollout_markers,
    ]
    payload["signature"] = (
        f"{payload.get('signature', '')}|direct-v1|swing:{len(bands)}|"
        f"rollover:{len(rollover_markers)}|macd-rollout:{len(macd_rollout_markers)}"
    )
    return payload


__all__ = [
    "MACD_INTRABAR_ROLLOUT_AT_V1",
    "MACD_INTRABAR_ROLLOUT_LABEL_V1",
    "build_lightweight_direct_live_payload_v1",
]
