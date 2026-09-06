from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from typing import Any

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from trading_desk import ChartBar, TIMEFRAME_MINUTES, utc
from trading_desk_chart import OVERLAY_NORMALIZED
from trading_desk_indicators import (
    INDICATOR_ATR,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    INDICATOR_VWAP,
    IndicatorPoint,
    TechnicalIndicators,
)


def _epoch_seconds(value: object) -> int:
    return int(utc(value).timestamp())


def _line(points: Sequence[IndicatorPoint]) -> list[dict[str, float | int]]:
    return [
        {"time": _epoch_seconds(point.bar_time), "value": float(point.value)}
        for point in points
    ]


def _candles(primary: Sequence[ChartBar]) -> list[dict[str, float | int]]:
    return [
        {
            "time": _epoch_seconds(bar.bar_time),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        }
        for bar in primary
    ]


def _volume(primary: Sequence[ChartBar]) -> list[dict[str, float | int | str]]:
    result: list[dict[str, float | int | str]] = []
    for bar in primary:
        if bar.volume is None or float(bar.volume) <= 0:
            continue
        result.append(
            {
                "time": _epoch_seconds(bar.bar_time),
                "value": float(bar.volume),
                "direction": "up" if float(bar.close) >= float(bar.open) else "down",
            }
        )
    return result


def _overlay_data(bars: Sequence[ChartBar], *, normalized: bool) -> list[dict[str, float | int]]:
    if not bars:
        return []
    base = float(bars[0].close)
    if normalized and base == 0.0:
        return []
    return [
        {
            "time": _epoch_seconds(bar.bar_time),
            "value": (100.0 * float(bar.close) / base) if normalized else float(bar.close),
        }
        for bar in bars
    ]


def _nearest_candle_time(candle_times: Sequence[int], value: int) -> int | None:
    if not candle_times:
        return None
    index = bisect_left(candle_times, value)
    candidates: list[int] = []
    if index < len(candle_times):
        candidates.append(candle_times[index])
    if index > 0:
        candidates.append(candle_times[index - 1])
    return min(candidates, key=lambda item: abs(item - value)) if candidates else None


def _marker_payload(
    markers: Sequence[AutoTraderTradeMarkerV1],
    *,
    candle_times: Sequence[int],
    timeframe: str,
) -> list[dict[str, Any]]:
    if not candle_times:
        return []
    bucket_seconds = TIMEFRAME_MINUTES[str(timeframe)] * 60
    first_time = candle_times[0]
    last_time = candle_times[-1]
    result: list[dict[str, Any]] = []
    for marker in markers:
        raw_time = _epoch_seconds(marker.executed_at)
        if raw_time < first_time - bucket_seconds or raw_time > last_time + bucket_seconds:
            continue
        bucket_time = raw_time - (raw_time % bucket_seconds)
        time_value = _nearest_candle_time(candle_times, bucket_time)
        if time_value is None:
            continue
        direction = str(marker.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        result.append(
            {
                "time": time_value,
                "price": float(marker.execution_price),
                "position": "atPriceMiddle",
                "shape": "arrowUp" if direction == "LONG" else "arrowDown",
                "color": "#16a34a" if direction == "LONG" else "#dc2626",
                "size": 1.0 if marker.active else 0.72,
                "id": f"{marker.net_position_id}:{raw_time}",
                "direction": direction,
                "active": bool(marker.active),
            }
        )
    result.sort(key=lambda item: int(item["time"]))
    return result


def _series(role: str, label: str, pane: str, data: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"role": role, "label": label, "pane": pane, "data": data, **extra}


def build_lightweight_live_payload_v1(
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
    """Build a renderer-neutral, JSON-safe LIVE chart contract for Lightweight Charts.

    The contract is presentation-only. It contains no execution requests, Saxo order
    payloads, sizing, approvals, or strategy authority.
    """

    selected = set(str(item) for item in indicator_names)
    candles = _candles(primary)
    candle_times = [int(item["time"]) for item in candles]
    lines: list[dict[str, Any]] = []
    histograms: list[dict[str, Any]] = []

    for overlay_name, bars in overlays.items():
        normalized = str(overlay_mode) == OVERLAY_NORMALIZED
        lines.append(
            _series(
                f"overlay:{overlay_name}",
                str(overlay_name),
                "price",
                _overlay_data(bars, normalized=normalized),
                price_scale=f"overlay:{overlay_name}",
                normalized=normalized,
            )
        )

    if indicators is not None:
        if INDICATOR_BOLLINGER in selected:
            lines.extend(
                [
                    _series("bollinger_upper", "Bollinger øvre", "price", _line(indicators.bollinger_upper)),
                    _series("bollinger_middle", "Bollinger midt", "price", _line(indicators.bollinger_middle)),
                    _series("bollinger_lower", "Bollinger nedre", "price", _line(indicators.bollinger_lower)),
                ]
            )
        if INDICATOR_VWAP in selected:
            lines.append(_series("vwap", "VWAP", "price", _line(indicators.vwap)))
        if INDICATOR_EMA20 in selected:
            lines.append(_series("ema20", "EMA 20", "price", _line(indicators.ema20)))
        if INDICATOR_EMA50 in selected:
            lines.append(_series("ema50", "EMA 50", "price", _line(indicators.ema50)))
        if INDICATOR_SMA50 in selected:
            lines.append(_series("sma50", "SMA 50", "price", _line(indicators.sma50)))
        if INDICATOR_MACD in selected:
            macd_tf = str(indicator_timeframes.get(INDICATOR_MACD, timeframe))
            lines.extend(
                [
                    _series("macd", f"MACD (12,26) · {macd_tf}", "macd", _line(indicators.macd)),
                    _series("macd_signal", f"Signal (9) · {macd_tf}", "macd", _line(indicators.macd_signal)),
                ]
            )
            histograms.append(
                _series("macd_histogram", f"MACD histogram · {macd_tf}", "macd", _line(indicators.macd_histogram))
            )
        if INDICATOR_RSI in selected:
            lines.append(_series("rsi", "RSI (14)", "rsi", _line(indicators.rsi)))
        if INDICATOR_STOCHASTIC in selected:
            lines.extend(
                [
                    _series("stochastic_k", "Stochastic %K", "stochastic", _line(indicators.stochastic_k)),
                    _series("stochastic_d", "Stochastic %D", "stochastic", _line(indicators.stochastic_d)),
                ]
            )
        if INDICATOR_ATR in selected:
            lines.append(_series("atr", "ATR (14)", "atr", _line(indicators.atr)))

    pane_order = ["price"]
    for pane in ("macd", "rsi", "stochastic", "atr"):
        if any(item["pane"] == pane for item in lines + histograms):
            pane_order.append(pane)

    signature = "|".join(
        [
            "lwc-live-v1",
            str(market),
            str(timeframe),
            ",".join(sorted(selected)),
            ",".join(pane_order),
            str(overlay_mode),
        ]
    )

    return {
        "version": 1,
        "chart_id": f"TradingDeskLightweight:{market}",
        "signature": signature,
        "market": str(market),
        "timeframe": str(timeframe),
        "height": int(chart_height),
        "price_panel_share": max(0.35, min(0.75, float(price_panel_share))),
        "candles": candles,
        "volume": _volume(primary),
        "lines": lines,
        "histograms": histograms,
        "markers": _marker_payload(trade_markers, candle_times=candle_times, timeframe=timeframe),
        "pane_order": pane_order,
        "thresholds": {
            "rsi": [30.0, 70.0],
            "stochastic": [20.0, 80.0],
        },
    }


__all__ = ["build_lightweight_live_payload_v1"]
