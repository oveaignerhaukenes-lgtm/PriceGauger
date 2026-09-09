from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from hypervigilant_macd_v1 import materialize_hypervigilant_macd_v1
from instrument_registry_v2 import list_subscribed_sources_v2
from saxo_chart_live import FormingCandleStore, forming_candle_event_age_seconds
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


_HV_MACD_LOOKBACK = timedelta(days=14)
_HV_MACD_MAX_BARS = 20_000
_HV_MACD_MAX_EVENT_AGE_SECONDS = 8.0


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


def _hypervigilant_macd_points_v1(
    *,
    market: str,
    timeframe: str,
) -> tuple[tuple[IndicatorPoint, ...], tuple[IndicatorPoint, ...], tuple[IndicatorPoint, ...]] | None:
    """Load the same exact-instrument provisional MACD series used by simple LIVE execution.

    This is presentation-only and fails open to the ordinary chart indicators if exact
    Saxo identity/history/forming data are unavailable. It never creates execution authority.
    """
    try:
        minutes = int(TIMEFRAME_MINUTES[str(timeframe)])
        sources = tuple(
            item for item in list_subscribed_sources_v2(provider="saxo")
            if str(item.market_name) == str(market)
        )
        if len(sources) != 1:
            return None
        source = sources[0]
        forming_store = FormingCandleStore()
        candle = forming_store.load(market=market)
        status = forming_store.load_status(market=market)
        if candle is None or status is None:
            return None
        if str(status.state).upper() != "STREAMING":
            return None
        if status.delayed_by_minutes is None or float(status.delayed_by_minutes) > 0.0:
            return None
        age = forming_candle_event_age_seconds(candle)
        if age is None or age > _HV_MACD_MAX_EVENT_AGE_SECONDS:
            return None
        if str(source.provider_instrument_id) != str(candle.uic):
            return None
        if source.asset_type is not None and str(source.asset_type) != str(candle.asset_type):
            return None

        end = datetime.now(timezone.utc)
        bars = CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(source.instrument_id),
            start=end - _HV_MACD_LOOKBACK,
            end=end,
            limit=_HV_MACD_MAX_BARS,
        )
        if not bars:
            return None
        observations = materialize_hypervigilant_macd_v1(
            tuple(item.point for item in bars),
            market=str(market),
            timeframe_minutes=minutes,
            forming_bar_time=candle.bar_time,
            forming_close=float(candle.close),
        )
        if not observations:
            return None
        macd = tuple(IndicatorPoint(bar_time=item.bar_time, value=float(item.macd)) for item in observations)
        signal = tuple(IndicatorPoint(bar_time=item.bar_time, value=float(item.signal)) for item in observations)
        histogram = tuple(IndicatorPoint(bar_time=item.bar_time, value=float(item.spread)) for item in observations)
        return macd, signal, histogram
    except Exception:
        return None


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
            shared = _hypervigilant_macd_points_v1(market=market, timeframe=macd_tf)
            if shared is None:
                macd_points, signal_points, histogram_points = (
                    indicators.macd,
                    indicators.macd_signal,
                    indicators.macd_histogram,
                )
                macd_label = f"MACD (12,26) · {macd_tf}"
            else:
                macd_points, signal_points, histogram_points = shared
                macd_label = f"MACD HV (12,26) · {macd_tf}"
            lines.extend(
                [
                    _series("macd", macd_label, "macd", _line(macd_points)),
                    _series("macd_signal", f"Signal (9) · {macd_tf}", "macd", _line(signal_points)),
                ]
            )
            histograms.append(
                _series("macd_histogram", f"MACD histogram · {macd_tf}", "macd", _line(histogram_points))
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
