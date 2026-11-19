"""Read-only, causal phase/timing research using the frozen V3 PAPER replay.

For every PAPER fill, inspect subsequent *observed* completed prices. These
outcomes are diagnostics, never inputs to a trade decision. No DB or Saxo I/O.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from statistics import mean

from strategy_lab_v2_replay import (
    MAX_BARS, ReplayCostsV2, ReplayResultV2, replay_v3_strategy_v2, utc,
)
from autotrader_v3_macd_stoch_v21_split_v3 import LONG_KEY_V3_PRICE_HIST


PAPER_WINDOWS = ("1m", "2m", "3m", "5m")
HORIZONS = (1, 3, 5)


@dataclass(frozen=True, slots=True)
class ResearchBarV1:
    """Minimal canonical shape needed by the existing pure strategy replay."""
    market_name: str
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


def _ordered_bars(bars):
    ordered = tuple(sorted(bars, key=lambda bar: utc(bar.bar_time)))
    if len(ordered) > MAX_BARS:
        raise ValueError(f"PAPER analysis accepts at most {MAX_BARS} 1m bars")
    previous = None
    for bar in ordered:
        stamp = utc(bar.bar_time)
        vals = tuple(float(getattr(bar, k)) for k in ("open", "high", "low", "close"))
        if (stamp.second or stamp.microsecond or
                not all(isfinite(x) and x > 0 for x in vals) or
                vals[2] > min(vals[0], vals[3]) or vals[1] < max(vals[0], vals[3]) or
                (previous is not None and stamp <= previous)):
            raise ValueError("Invalid/duplicate canonical minute bars")
        previous = stamp
    return ordered


def _state_before(ordered, index: int, lookback: int = 20) -> str:
    """State known strictly *before* the event fill at this minute's open."""
    if index < lookback + 1:
        return "Ukjent"
    previous = ordered[index - lookback - 1:index]
    if any(utc(b.bar_time) - utc(a.bar_time) != timedelta(minutes=1)
           for a, b in zip(previous, previous[1:])):
        return "Ukjent"
    closes = [float(x.close) for x in previous]
    path = sum(abs(b-a) for a, b in zip(closes, closes[1:]))
    if path <= 1e-9:
        return "Ukjent"
    efficiency = abs(closes[-1] - closes[0]) / path
    return "Trend" if efficiency >= .60 else "Oscillerende" if efficiency <= .30 else "Blandet"


def phase_outcomes_v1(bars, result: ReplayResultV2) -> list[dict]:
    """Count post-fill adverse entries and post-exit favorable rebounds.

    Horizons are consecutive observed 1m closes after fill at the next open.
    A gap or end-of-sample censors the event; zero-change is never 'adverse'.
    """
    ordered = _ordered_bars(bars)
    by_time = {utc(bar.bar_time): i for i, bar in enumerate(ordered)}
    grouped = defaultdict(list)
    for event in result.events:
        if event.kind not in ("OPEN", "ADD", "CLOSE"):
            continue
        index = by_time.get(utc(event.at))
        if index is None:
            continue
        side = (1 if event.after_lots > 0 else -1) if event.kind != "CLOSE" else (
            1 if event.prior_lots > 0 else -1)
        if not side:
            continue
        kind = "Inngang/økning" if event.kind != "CLOSE" else "Flat-utgang"
        state = _state_before(ordered, index)
        for minutes in HORIZONS:
            subset = ordered[index:index + minutes]
            if len(subset) != minutes or any(
                utc(b.bar_time)-utc(a.bar_time) != timedelta(minutes=1)
                for a, b in zip(subset, subset[1:])
            ):
                continue
            last_end = utc(subset[-1].bar_time) + timedelta(minutes=1)
            if last_end != utc(event.at) + timedelta(minutes=minutes):
                continue
            signed_points = side * (float(subset[-1].close) - float(event.price))
            grouped[(kind, state, minutes)].append(signed_points)

    output = []
    for (kind, state, horizon), moves in sorted(grouped.items()):
        if kind == "Inngang/økning":
            damaging = sum(move < 0 for move in moves)
            label = "Mot posisjonen"
        else:
            damaging = sum(move > 0 for move in moves)
            label = "Tilbake i forlatt retning"
        output.append({
            "Hendelse":kind, "Markedstilstand":state, "Etter min":horizon,
            "Antall":len(moves), "Feilfase":label,
            "Feilfase %":round(100 * damaging / len(moves), 1),
            "Snitt videre punkter (posisjonsretning)":round(mean(moves), 2),
        })
    return output


def compare_long_regime_clocks_v1(bars, costs: ReplayCostsV2) -> dict:
    """Same exact bars, R10 / E2, only S clock varies; never touch LIVE.

    Net PAPER NAV includes the caller's *manual* cost model, not Saxo fills.
    Market-state labels use 20 prices all known before a PAPER fill.
    """
    ordered = _ordered_bars(bars)
    if len(ordered) < 600:
        raise ValueError("Need at least 600 real 1m bars for R10 MACD warmup")
    contiguous = 1
    longest = 1
    for old, new in zip(ordered, ordered[1:]):
        contiguous = contiguous + 1 if utc(new.bar_time)-utc(old.bar_time) == timedelta(minutes=1) else 1
        longest = max(longest, contiguous)
    if longest < 350:
        raise ValueError("Insufficient contiguous 1m history for R10 MACD warmup")
    summary, phases, failures = [], {}, {}
    for clock in PAPER_WINDOWS:
        try:
            result = replay_v3_strategy_v2(
                strategy_key=LONG_KEY_V3_PRICE_HIST, bars=ordered,
                costs=costs, timeframe=clock,
                regime_timeframe="10m", exit_timeframe="2m",
            )
            phase = phase_outcomes_v1(ordered, result)
            entries = [e for e in result.events if e.kind in ("OPEN", "ADD")]
            summary.append({
                "Signal":clock, "PAPER netto %":round(result.net_return_pct, 2),
                "Handler":result.trades, "Innganger/økninger":len(entries),
                "PAPER kostnad NOK":round(result.total_cost_nok, 2),
                "Maks DD %":round(result.drawdown_pct, 2),
                "Databrudd":result.skipped_gaps,
            })
            phases[clock] = phase
        except (ValueError, IndexError, ZeroDivisionError) as exc:
            failures[clock] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return {"bars":len(ordered),
            "from":utc(ordered[0].bar_time), "to":utc(ordered[-1].bar_time),
            "summary":summary, "phase":phases, "failures":failures}


__all__ = ["PAPER_WINDOWS", "HORIZONS", "ResearchBarV1", "phase_outcomes_v1",
           "compare_long_regime_clocks_v1"]
