"""Incremental, causal technical features for Live-Sim Lab. No broker imports."""
from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from statistics import pstdev


TIMEFRAMES = (2, 5, 10, 15, 30)
FEATURE_VERSION = "lab-features-v1"


def utc(value):
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def initial_features():
    return {"version": FEATURE_VERSION, "last_bar": None, "last_close": None,
            "returns": [], "macd": {}, "regime": "WARMUP", "tags": []}


def _ema(previous, value, period):
    return value if previous is None else previous + (2.0 / (period + 1)) * (value - previous)


def _update_macd(current, close):
    fast = _ema(current.get("fast"), close, 12)
    slow = _ema(current.get("slow"), close, 26)
    line = fast - slow
    signal = _ema(current.get("signal"), line, 9)
    histogram = line - signal
    return {"fast": fast, "slow": slow, "signal": signal,
            "spread": line, "hist": histogram,
            "prev_hist": current.get("hist"), "prev_spread": current.get("spread"),
            "closed_count": int(current.get("closed_count", 0)) + 1}


def technical_regime(returns):
    """Ex ante classification using only returns already observed at bar close."""
    if len(returns) < 30:
        return "WARMUP", []
    recent = returns[-12:]
    long = returns[-60:]
    short_vol = pstdev(recent)
    long_vol = pstdev(long)
    changes = sum(a * b < 0 for a, b in zip(recent, recent[1:]))
    efficiency = abs(sum(recent)) / max(1e-12, sum(abs(r) for r in recent))
    impulse = abs(sum(recent[-5:])) / max(1e-12, sum(abs(r) for r in recent[-5:]))
    tags = []
    if short_vol > max(0.00001, 1.5 * long_vol):
        tags.append("HIGH_VOL")
    if changes >= 7 and efficiency < 0.35:
        tags.append("WHIPSAW")
    if impulse > 0.88 and abs(sum(recent[-5:])) > max(0.0005, 2.5 * long_vol):
        tags.append("IMPULSE")
    if efficiency > 0.65:
        tags.append("TREND")
    return (tags[0] if tags else "RANGE"), tags


def advance_features(state, *, bar_time, close):
    """Call once per CLOSED canonical 1m candle, shared by all lab variants.

    MACD windows use UTC-aligned completed timeframe bars. No in-progress higher
    timeframe candle is used and the same bar is never processed twice.
    """
    when = utc(bar_time)
    stamp = when.isoformat()
    if state["last_bar"] is not None and stamp <= state["last_bar"]:
        raise ValueError("Live-Sim Lab features require strictly increasing closed bars")
    price = float(close)
    if not 0 < price < float("inf"):
        raise ValueError("invalid close")
    previous = state.get("last_close")
    values = list(state.get("returns", []))
    if previous and previous > 0:
        values.append(price / float(previous) - 1.0)
    values = values[-120:]
    indicators = dict(state.get("macd", {}))
    minute = int(when.timestamp()) // 60
    for tf in TIMEFRAMES:
        if (minute + 1) % tf == 0:
            indicators[str(tf)] = _update_macd(indicators.get(str(tf), {}), price)
    regime, tags = technical_regime(values)
    return {"version": FEATURE_VERSION, "last_bar": stamp, "last_close": price,
            "returns": values, "macd": indicators, "regime": regime, "tags": tags}


def _direction(value, deadband=0.0):
    return 1 if value > deadband else -1 if value < -deadband else 0


def experiment_decision(config, state, features, *, bar_time):
    """Propose next-minute exposure; never read future prices or broker state.

    These are LAB-NATIVE MACD research prototypes, not bit-identical replicas
    of production Aen#2 or Aen#2.1.
    """
    tf = int(config["signal_tf"])
    minute = int(utc(bar_time).timestamp()) // 60
    if (minute + 1) % tf:
        return None, "WAIT_SIGNAL_BAR"
    signal = features["macd"].get(str(tf), {})
    regime = features["macd"].get(str(int(config["regime_tf"])), {})
    if min(signal.get("closed_count", 0), regime.get("closed_count", 0)) < 35:
        return None, "WARMUP_MACD"
    spread, prev = regime["spread"], regime["prev_spread"]
    if prev is None or signal.get("prev_hist") is None:
        return None, "WARMUP_MACD"
    # Small deadband reduces noise in sticky; fast-exit reacts to zero-cross.
    deadband = (abs(spread) * 0.03) if config["family"] == "sticky" else 0.0
    side = _direction(spread, deadband)
    current = float(state.get("exposure", 0.0))
    max_exposure = float(config["max_exposure"])
    step = max_exposure / 2.0
    hist = signal["hist"]
    prev_hist = signal["prev_hist"]
    momentum = hist - prev_hist
    if side == 0 or (side * current < 0):
        target, reason = 0.0, "REGIME_EXIT"
    elif side * momentum > 0:
        target, reason = side * min(max_exposure, abs(current) + step), "BUILD"
    elif config["family"] == "fast_exit" and side * hist < 0:
        target, reason = 0.0, "FAST_EXIT"
    elif side * momentum < 0 and side * (spread - prev) < 0:
        target, reason = side * max(0.0, abs(current) - step), "REDUCE"
    else:
        target, reason = current, "HOLD"
    if config["modifier"] == "whipsaw_pause" and "WHIPSAW" in features["tags"]:
        if abs(target) > abs(current) and target * current >= 0:
            target, reason = current, "WHIPSAW_PAUSE"
    if config["modifier"] == "impulse_exit" and current and "IMPULSE" in features["tags"]:
        recent = features["returns"][-5:]
        if sum(recent) * current < 0:
            target, reason = 0.0, "ADVERSE_IMPULSE_EXIT"
    return round(target, 6), reason


def settle_bar(config, state, features, *, bar_time, open_price, close_price):
    """Paper fill at NEXT bar open, after previous closed-bar decision.

    Fractional exposure represents normalized notional / NAV; figures are not
    broker-lot P&L. A conservative turnover cost is charged on each paper fill.
    """
    result = dict(state)
    cash = float(result.get("equity", 10000.0))
    prev = result.get("last_close")
    exposure = float(result.get("exposure", 0.0))
    opening = float(open_price)
    closing = float(close_price)
    if min(opening, closing) <= 0:
        raise ValueError("nonpositive price")
    if prev and float(prev) > 0:
        cash *= 1.0 + exposure * (opening / float(prev) - 1.0)
    target = result.pop("pending", None)
    traded = False
    if target is not None and abs(float(target) - exposure) > 1e-8:
        change = abs(float(target) - exposure)
        cash *= 1.0 - change * float(config["cost_bps"]) / 10000.0
        exposure = float(target)
        result["trades"] = int(result.get("trades", 0)) + 1
        traded = True
    cash *= 1.0 + exposure * (closing / opening - 1.0)
    peak = max(float(result.get("peak", 10000.0)), cash)
    last_equity = float(state.get("equity", 10000.0))
    result.update(equity=cash, peak=peak, exposure=exposure, last_close=closing,
                  last_bar=utc(bar_time).isoformat(), max_drawdown=max(
                      float(result.get("max_drawdown", 0.0)), 1.0 - cash / max(peak, 1e-9)))
    target, reason = experiment_decision(config, result, features, bar_time=bar_time)
    if target is not None:
        result["pending"] = target
    return result, {"bar_time": utc(bar_time).isoformat(), "equity": cash,
                    "exposure": exposure, "delta_equity": cash - last_equity,
                    "regime": features["regime"], "tags": features["tags"],
                    "trade": traded, "decision": reason, "pending": target}
