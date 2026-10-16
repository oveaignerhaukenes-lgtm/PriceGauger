"""Read-only, causal-input Tech100 regime forensics around Oct 16, 2026.

The market diagnostics use fully observed canonical minute OHLC; the 30-minute
rolling labels use only already closed input bars. Whole-period summaries are
RETROSPECTIVE and must not be mistaken for actionable advance regime signals.
No broker, V3 strategy, persistence writes, or Saxo authority is imported here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import statistics
from typing import Any, Sequence

WINDOWS_20261016 = (
    ("oct13_same_clock", "2026-10-13T11:48:00Z", "2026-10-13T16:15:00Z"),
    ("oct14_same_clock", "2026-10-14T11:48:00Z", "2026-10-14T16:15:00Z"),
    ("oct15_same_clock", "2026-10-15T11:48:00Z", "2026-10-15T16:15:00Z"),
    ("oct16_before_cash_open", "2026-10-16T11:48:00Z", "2026-10-16T13:29:00Z"),
    ("oct16_after_cash_open", "2026-10-16T13:30:00Z", "2026-10-16T16:15:00Z"),
    ("oct16_screenshot_window", "2026-10-16T11:48:00Z", "2026-10-16T16:15:00Z"),
)


def utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_get(row: Any, name: str, index: int) -> Any:
    return row[name] if isinstance(row, dict) else row[index]


def _sample_regime(prices: Sequence[float]) -> tuple[str, float, float]:
    """Closed-bar observation only; same thresholds as existing Scoreboard v1."""
    if len(prices) < 12:
        return "UNKNOWN", 0.0, 0.0
    changes = [b - a for a, b in zip(prices, prices[1:])]
    travel = sum(abs(x) for x in changes)
    efficiency = abs(sum(changes)) / travel if travel else 0.0
    signs = [1 if x > 0 else -1 for x in changes if x]
    reversal = (sum(a != b for a, b in zip(signs, signs[1:])) / (len(signs) - 1)
                if len(signs) > 1 else 0.0)
    impulse = sum(sorted((abs(x) for x in changes), reverse=True)[:3]) / travel if travel else 0.0
    if impulse >= 0.28:
        label = "IMPULSE"
    elif efficiency >= 0.42 and reversal <= 0.52:
        label = "TREND"
    elif efficiency <= 0.16 and reversal >= 0.52:
        label = "CHOPPY"
    else:
        label = "EVEN"
    return label, efficiency, reversal


def quantify_market_window(bars: Sequence[Any], *, start: Any, end: Any) -> dict[str, Any]:
    """Compute comparable 1m-market measurements; gaps are never filled synthetically."""
    left, right = utc(start), utc(end)
    selected = sorted(
        (bar for bar in bars if left <= utc(bar.bar_time) <= right),
        key=lambda bar: utc(bar.bar_time),
    )
    expected = max(1, int((right - left).total_seconds() // 60) + 1)
    answer: dict[str, Any] = {
        "start_utc": left.isoformat(), "end_utc": right.isoformat(),
        "bars": len(selected), "expected_clock_minutes": expected,
        "coverage_pct": round(len(selected) * 100.0 / expected, 2),
        "gaps": 0, "contiguous_pairs": 0,
    }
    if len(selected) < 12:
        answer["status"] = "INSUFFICIENT_MARKET_DATA"
        return answer

    changes: list[float] = []
    log_bp: list[float] = []
    sign_pairs: list[tuple[int, int]] = []
    last_sign: int | None = None
    last_at: datetime | None = None
    for prior, current in zip(selected, selected[1:]):
        at = utc(current.bar_time)
        consecutive = at - utc(prior.bar_time) == timedelta(minutes=1)
        if not consecutive:
            answer["gaps"] += 1
            last_sign = None
            last_at = None
            continue
        change = float(current.close) - float(prior.close)
        changes.append(change)
        if float(prior.close) > 0 and float(current.close) > 0:
            log_bp.append(math.log(float(current.close) / float(prior.close)) * 10000.0)
        if change:
            sign = 1 if change > 0 else -1
            if last_sign is not None and last_at == utc(prior.bar_time):
                sign_pairs.append((last_sign, sign))
            last_sign, last_at = sign, at
        else:
            last_sign = None
            last_at = None

    answer["contiguous_pairs"] = len(changes)
    if len(changes) < 10:
        answer["status"] = "INSUFFICIENT_CONTIGUOUS_MARKET_DATA"
        return answer

    abs_changes = [abs(x) for x in changes]
    travel = sum(abs_changes)
    reversal_rate = sum(a != b for a, b in sign_pairs) / len(sign_pairs) if sign_pairs else 0.0
    rolling: dict[str, int] = {"CHOPPY": 0, "EVEN": 0, "TREND": 0, "IMPULSE": 0}
    # A regime observation is recorded each 5 minutes, using ONLY the 30
    # already available continuous bars ending at that observation.
    for i in range(29, len(selected), 5):
        sample = selected[i - 29:i + 1]
        if any(utc(b.bar_time) - utc(a.bar_time) != timedelta(minutes=1)
               for a, b in zip(sample, sample[1:])):
            continue
        label, _, _ = _sample_regime([float(x.close) for x in sample])
        if label in rolling:
            rolling[label] += 1
    total_rolling = sum(rolling.values())
    n_top = max(1, math.ceil(len(abs_changes) * 0.1))
    answer.update({
        "status": "OK",
        "first_price": round(float(selected[0].close), 3),
        "last_price": round(float(selected[-1].close), 3),
        "market_move_pct": round((float(selected[-1].close) / float(selected[0].close) - 1) * 100, 4)
                           if selected[0].close else None,
        "market_move_points": round(float(selected[-1].close) - float(selected[0].close), 3),
        # Sum only contiguous observed moves; do not attribute missing-session gaps.
        "net_observed_points": round(sum(changes), 3),
        "travel_observed_points": round(travel, 3),
        "efficiency_ratio": round(abs(sum(changes)) / travel, 4) if travel else 0,
        "sign_reversal_rate": round(reversal_rate, 4),
        "mean_abs_1m_points": round(statistics.mean(abs_changes), 3),
        "volatility_1m_bp": round(statistics.stdev(log_bp), 3) if len(log_bp) > 1 else None,
        "top_10pct_impulse_share": round(sum(sorted(abs_changes, reverse=True)[:n_top]) / travel, 4)
                                   if travel else 0,
        "rolling30_samples": total_rolling,
        "rolling30_regime_pct": {k: round(100 * v / total_rolling, 1) if total_rolling else None
                                 for k, v in rolling.items()},
        "coverage_warning": len(selected) < expected * 0.8 or bool(answer["gaps"]),
    })
    return answer


def _macd_cross_times(bars: Sequence[Any], timeframe_minutes: int) -> tuple[datetime, ...]:
    """Use the existing closed-bar MACD signal implementation; no new signal rules."""
    from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
    if len(bars) < 40 * int(timeframe_minutes):
        return ()
    closed = closed_bars_v2(
        tuple((str(b.bar_time), float(b.close)) for b in bars),
        market=str(bars[0].market_name), timeframe_minutes=int(timeframe_minutes),
    )
    observations = macd_observations_v2(closed, timeframe_minutes=int(timeframe_minutes))
    crosses: list[datetime] = []
    for before, after in zip(observations, observations[1:]):
        if utc(after.closed_at) - utc(before.closed_at) != timedelta(minutes=timeframe_minutes):
            continue
        if before.spread <= 0 < after.spread or before.spread >= 0 > after.spread:
            crosses.append(utc(after.closed_at))
    return tuple(crosses)


def _execution_counts(*, db_path: str, uic: int, start: datetime, end: datetime) -> dict[str, Any]:
    """Count reconciled V3 execution events, not deals/profit or manual Saxo orders."""
    from database import connect
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT instance_id, action, COUNT(*) AS n, COALESCE(SUM(amount), 0) AS units
               FROM autotrader_v3_execution_events
               WHERE uic=? AND executed_at>=? AND executed_at<?
               GROUP BY instance_id,action ORDER BY instance_id,action""",
            (int(uic), start, end + timedelta(minutes=1)),
        ).fetchall()
    counts: dict[str, dict[str, Any]] = {}
    for row in rows:
        instance = str(_row_get(row, "instance_id", 0))
        action = str(_row_get(row, "action", 1))
        group = counts.setdefault(instance, {"events": 0, "lots_changed": 0.0, "actions": {}})
        n, lots = int(_row_get(row, "n", 2)), float(_row_get(row, "units", 3))
        group["events"] += n
        group["lots_changed"] += lots
        group["actions"][action] = n
    for group in counts.values():
        group["lots_changed"] = round(group["lots_changed"], 3)
    return counts


def production_tech100_regime_study(*, db_path: str = "pricegauger.db", now: Any = None) -> dict[str, Any]:
    """One-time, bounded read-only comparison; never infer causal LIVE P/L."""
    from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
    from database import connect
    moment = utc(now or datetime.now(timezone.utc))
    complete_cutoff = utc("2026-10-16T16:16:00Z")
    if moment < complete_cutoff:
        return {"status": "WAITING_FOR_COMPLETE_WINDOW"}
    with connect(db_path) as db:
        row = db.execute(
            """SELECT instrument_id, market_name, uic FROM autotrader_v3_engine_instances
               WHERE enabled=TRUE AND uic=4912
               ORDER BY instrument_id LIMIT 1"""
        ).fetchone()
    if row is None:
        return {"status": "NO_ACTIVE_TECH100_INSTRUMENT"}
    instrument_id = int(_row_get(row, "instrument_id", 0))
    market_name = str(_row_get(row, "market_name", 1))
    uic = int(_row_get(row, "uic", 2))
    # 5 days, <8k 1m bars. Extra one-day warmup for consistent MACD 5m.
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=instrument_id,
        start=utc("2026-10-12T00:00:00Z"),
        end=complete_cutoff,
        limit=8500,
    )
    crosses = {tf: _macd_cross_times(bars, tf) for tf in (2, 5, 10)}
    windows = []
    for name, start, end in WINDOWS_20261016:
        a, b = utc(start), utc(end)
        measurement = quantify_market_window(bars, start=a, end=b)
        measurement["name"] = name
        measurement["macd_crosses"] = {
            str(tf): sum(a <= x < b + timedelta(minutes=1) for x in clocks)
            for tf, clocks in crosses.items()
        }
        try:
            measurement["v3_reconciled"] = _execution_counts(db_path=db_path, uic=uic, start=a, end=b)
        except Exception as exc:
            measurement["v3_execution_evidence"] = f"UNAVAILABLE_{type(exc).__name__}"
        windows.append(measurement)
    return {
        "status": "OK", "source": "CANONICAL_1M_CLOSED_BARS_AND_V3_RECONCILED_EVENTS",
        "market": market_name, "uic": uic, "instrument_id": instrument_id,
        "bar_source_count": len(bars), "analyzed_at": moment.isoformat(),
        "notes": (
            "Descriptive and partly hindsight windows; not per-strategy realized P/L. "
            "Do not infer profitability, predict regimes, or auto-switch LIVE."
        ),
        "windows": windows,
    }


def emit_tech100_regime_study(logger: Any, *, db_path: str = "pricegauger.db", now: Any = None) -> bool:
    result = production_tech100_regime_study(db_path=db_path, now=now)
    logger.info("REGIME_STUDY_META %s", json.dumps(
        {k: v for k, v in result.items() if k != "windows"},
        default=str, separators=(",", ":"), ensure_ascii=False))
    if result.get("status") != "OK":
        return False
    for row in result["windows"]:
        logger.info("REGIME_STUDY_WINDOW %s", json.dumps(
            row, default=str, separators=(",", ":"), ensure_ascii=False))
    return True


__all__ = [
    "WINDOWS_20261016", "quantify_market_window", "production_tech100_regime_study",
    "emit_tech100_regime_study",
]
