from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
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


_V3_ACCOUNT_PALETTES = (
    ("#d8b4fe", "#7e22ce"),
    ("#67e8f9", "#0e7490"),
    ("#fcd34d", "#b45309"),
    ("#86efac", "#15803d"),
    ("#fda4af", "#be123c"),
    ("#93c5fd", "#1d4ed8"),
    ("#fdba74", "#c2410c"),
    ("#a5b4fc", "#4338ca"),
    ("#5eead4", "#0f766e"),
    ("#f9a8d4", "#be185d"),
    ("#bef264", "#4d7c0f"),
    ("#c4b5fd", "#6d28d9"),
)


def _v3_account_palette(account_id: str) -> tuple[str, str]:
    key = str(account_id or "unknown").encode("utf-8")
    index = int.from_bytes(hashlib.blake2s(key, digest_size=2).digest(), "big")
    return _V3_ACCOUNT_PALETTES[index % len(_V3_ACCOUNT_PALETTES)]


def _v3_execution_marker_size(action: str) -> float:
    normalized = str(action or "").upper()
    if normalized in {"OPEN", "ADD"}:
        return 0.46
    if normalized in {"REDUCE", "CLOSE"}:
        return 0.30
    if normalized in {"REVERSE", "FLIP"}:
        return 0.62
    return 0.38


def _v3_account_palette_map(
    markers: Sequence[AutoTraderTradeMarkerV1],
) -> dict[str, tuple[str, str]]:
    account_ids = sorted({
        str(marker.account_id or "").strip()
        for marker in markers
        if str(marker.source or "") == "AUTOTRADER_V3"
        and str(marker.account_id or "").strip()
    })
    return {
        account_id: _V3_ACCOUNT_PALETTES[index % len(_V3_ACCOUNT_PALETTES)]
        for index, account_id in enumerate(account_ids)
    }


def _marker_accounts(markers: Sequence[AutoTraderTradeMarkerV1]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    palette_map = _v3_account_palette_map(markers)
    for marker in markers:
        if str(marker.source or "") != "AUTOTRADER_V3":
            continue
        account_id = str(marker.account_id or "").strip()
        if not account_id or account_id in result:
            continue
        light, dark = palette_map.get(account_id, _v3_account_palette(account_id))
        result[account_id] = {
            "account_id": account_id,
            "label": str(marker.account_name or account_id),
            "light": light,
            "dark": dark,
        }
    return [result[key] for key in sorted(result)]


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
    palette_map = _v3_account_palette_map(markers)
    for marker in markers:
        raw_time = _epoch_seconds(marker.executed_at)
        if raw_time < first_time - bucket_seconds or raw_time > last_time + bucket_seconds:
            continue
        bucket_time = raw_time - (raw_time % bucket_seconds)
        time_value = _nearest_candle_time(candle_times, bucket_time)
        if time_value is None:
            continue
        direction = str(marker.direction).upper()
        if direction not in {"LONG", "SHORT", "FLAT"}:
            continue
        source = str(marker.source or "")
        manual_saxo = source == "SAXO_MANUAL_FILL"
        auto_v3 = source == "AUTOTRADER_V3"
        auto_v2 = source in {"AUTOTRADER_V2", "AUTOTRADER_OPEN", "ACTIVE_MANAGED_POSITION"}
        is_flat = direction == "FLAT"

        if auto_v3:
            side = str(marker.side or "").upper()
            if side not in {"BUY", "SELL"}:
                side = "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else "")
            if side not in {"BUY", "SELL"}:
                continue
            account_id = str(marker.account_id or "").strip()
            light, dark = palette_map.get(
                account_id,
                _v3_account_palette(str(marker.account_id or marker.instance_id or marker.strategy_key)),
            )
            visual_direction = "LONG" if side == "BUY" else "SHORT"
            action = str(marker.action or "").upper()
            result.append(
                {
                    "time": time_value,
                    "price": float(marker.execution_price),
                    "position": "belowBar" if side == "BUY" else "aboveBar",
                    "shape": "arrowUp" if side == "BUY" else "arrowDown",
                    "color": light if side == "BUY" else dark,
                    "text": "",
                    "size": _v3_execution_marker_size(action),
                    "id": f"{source}:{marker.net_position_id}:{raw_time}:execution",
                    "direction": visual_direction,
                    "position_direction": direction,
                    "active": bool(marker.active),
                    "source": source,
                    "marker_role": "EXECUTION_EVENT",
                    "action": action,
                    "side": side,
                    "account_id": str(marker.account_id or ""),
                    "account_name": str(marker.account_name or ""),
                    "instance_id": str(marker.instance_id or marker.strategy_key or ""),
                    "inventory_before": marker.inventory_before,
                    "inventory_after": marker.inventory_after,
                }
            )
            continue

        if is_flat:
            color = "#ef4444"
            label = "FLAT"
            size = 1.2
        elif manual_saxo:
            # Manual broker activity stays explicit on the chart.
            color = "#16a34a" if direction == "LONG" else "#dc2626"
            label = "M"
            size = 0.82
        else:
            color = "#0ea5e9"
            label = ""
            size = 1.0 if marker.active else 0.72
        result.append(
            {
                "time": time_value,
                "price": float(marker.execution_price),
                "position": "atPriceMiddle",
                "shape": "circle" if is_flat else ("arrowUp" if direction == "LONG" else "arrowDown"),
                "color": color,
                "text": label,
                "size": size,
                "id": f"{source}:{marker.net_position_id}:{raw_time}",
                "direction": direction,
                "active": bool(marker.active),
                "source": source,
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
    marker_times: Sequence[int] = (),
) -> dict[str, Any]:
    """Build a renderer-neutral, JSON-safe LIVE chart contract for Lightweight Charts.

    The contract is presentation-only. It contains no execution requests, Saxo order
    payloads, sizing, approvals, or strategy authority.
    """

    selected = set(str(item) for item in indicator_names)
    candles = _candles(primary)
    candle_times = [int(item["time"]) for item in candles]
    marker_candle_times = sorted({
        *candle_times,
        *(int(value) for value in marker_times),
    })
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
        "markers": _marker_payload(trade_markers, candle_times=marker_candle_times, timeframe=timeframe),
        "marker_accounts": _marker_accounts(trade_markers),
        "pane_order": pane_order,
        "thresholds": {
            "rsi": [30.0, 70.0],
            "stochastic": [20.0, 80.0],
        },
    }


__all__ = ["build_lightweight_live_payload_v1"]
