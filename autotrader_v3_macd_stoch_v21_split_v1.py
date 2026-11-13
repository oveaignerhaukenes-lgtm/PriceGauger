"""MACD+Stoch V2.1 independent LONG/FLAT and SHORT/FLAT with R/entry/exit clocks.

Pure target producer. The frozen MACD+Stoch V2.1 decision function is used
unchanged for entries and pyramiding; a separately completed MACD clock
decides exits. A third completed MACD clock grants one-way regime authority.
No broker calls, account mutation, or arbitrary state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from trading_desk import ChartBar

LONG_KEY_V3 = "macd-stoch-v21-r-long-flat-v1"
SHORT_KEY_V3 = "macd-stoch-v21-r-short-flat-v1"
SPLIT_KEYS_V3 = frozenset((LONG_KEY_V3, SHORT_KEY_V3))
ALLOWED_CLOCKS_V3 = frozenset((1, 2, 5, 10, 15, 30, 60))


def _utc(raw):
    stamp = raw if isinstance(raw, datetime) else datetime.fromisoformat(
        str(raw).replace("Z", "+00:00")
    )
    if stamp.tzinfo is None:
        raise ValueError("Timezone-aware source bars required")
    return stamp.astimezone(timezone.utc)


def _completed_bars(source_bars: Sequence, *, timeframe: int, cutoff, market: str):
    """Only exact, gap-free and fully finished OHLC buckets. No partial 30m."""
    minutes = int(timeframe)
    if minutes not in ALLOWED_CLOCKS_V3:
        raise ValueError("Unsupported MACD timeframe")
    cutoff = _utc(cutoff)
    groups = {}
    for row in source_bars:
        start = _utc(row.bar_time)
        if start >= cutoff:
            continue
        stamp = start.replace(
            minute=(start.minute // minutes) * minutes, second=0, microsecond=0
        ) if minutes <= 60 else start
        groups.setdefault(stamp, []).append((start, row))
    complete = []
    for beginning, members in sorted(groups.items()):
        end = beginning + timedelta(minutes=minutes)
        if end > cutoff or len(members) != minutes:
            continue
        members.sort(key=lambda part: part[0])
        if any(t != beginning + timedelta(minutes=i)
               for i, (t, _) in enumerate(members)):
            continue
        rows = [row for _, row in members]
        op, hi, lo, cl = (float(rows[0].open),
                          max(float(b.high) for b in rows),
                          min(float(b.low) for b in rows),
                          float(rows[-1].close))
        if not all(isfinite(x) and x > 0 for x in (op, hi, lo, cl)):
            continue
        if lo > min(op, cl) or hi < max(op, cl):
            continue
        complete.append(ChartBar(
            market=market, bar_time=beginning, open=op, high=hi,
            low=lo, close=cl, volume=None,
        ))
    return tuple(complete)


def _latest_macd(source_bars: Sequence, *, minutes: int, cutoff, market: str):
    bars = _completed_bars(
        source_bars, timeframe=minutes, cutoff=cutoff, market=market
    )
    if len(bars) < 35:
        return None
    observations = macd_observations_v2(
        bars, timeframe_minutes=int(minutes)
    )
    if not observations:
        return None
    current = observations[-1]
    # Stale macro data cannot authorize a new entry after a market closure
    # or provider outage; the next full bucket reestablishes eligibility.
    if _utc(cutoff) - _utc(current.closed_at) > timedelta(minutes=minutes):
        return None
    spread = float(current.spread)
    return spread if isfinite(spread) else None


def _decision(*, amount: float, action: str, reason: str,
              observation, base=None) -> MacdStochV2DecisionV3:
    return MacdStochV2DecisionV3(
        TargetInventoryV3(round(amount, 10)), action, reason,
        float(observation.spread),
        0.0 if base is None else base.composite_score,
        0.0 if base is None else base.macd_component,
        0.0 if base is None else base.stoch_component,
    )


def split_target_v3(
    *, side: int, current_target: TargetInventoryV3, observation,
    previous_observation=None, bars=(), source_bars=(),
    regime_timeframe_minutes: int = 30,
    exit_timeframe_minutes: int = 2,
    market_name: str = "",
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochV2DecisionV3:
    """1m/selected entry V2.1; selected exit MACD; selected macro regime.

    A slower exit ignores weak/opposing entry-clock signals for *existing*
    exposure, without ever opening/building on those opposing signals.
    """
    if side not in (-1, 1):
        raise ValueError("Split strategy side must be +1 or -1")
    if int(regime_timeframe_minutes) not in ALLOWED_CLOCKS_V3:
        raise ValueError("Unsupported regime timeframe")
    if int(exit_timeframe_minutes) not in ALLOWED_CLOCKS_V3:
        raise ValueError("Unsupported exit timeframe")
    cutoff = getattr(observation, "closed_at", observation.bar_time)
    current = float(current_target.amount)
    if current * side < -1e-9:
        return _decision(amount=0, action="WRONG_SIDE_FLAT",
                         reason="Split strategy refuses opposite inventory", observation=observation)
    macro = _latest_macd(source_bars, minutes=int(regime_timeframe_minutes),
                         cutoff=cutoff, market=market_name)
    exit_macd = _latest_macd(source_bars, minutes=int(exit_timeframe_minutes),
                             cutoff=cutoff, market=market_name)
    if macro is None or exit_macd is None:
        return _decision(amount=0, action="CLOCK_UNAVAILABLE_FLAT",
                         reason="Missing/stale fully closed regime or exit MACD; no exposure",
                         observation=observation)
    if side * macro <= 0:
        return _decision(amount=0, action="REGIME_FLAT",
                         reason=f"R{regime_timeframe_minutes} MACD {macro:+.5g} disallows side {side:+d}",
                         observation=observation)
    if side * exit_macd <= 0:
        return _decision(amount=0, action="EXIT_MACD_FLAT",
                         reason=f"E{exit_timeframe_minutes} MACD {exit_macd:+.5g} against side {side:+d}",
                         observation=observation)
    base = macd_stoch_v21_target_v3(
        current_target=TargetInventoryV3(current),
        observation=observation, previous_observation=previous_observation,
        bars=bars, config=config,
    )
    proposed = float(base.target.amount)
    clock_note = (f"R{regime_timeframe_minutes}={macro:+.5g}; "
                  f"EXIT{exit_timeframe_minutes}={exit_macd:+.5g}; "
                  f"ENTRY V2.1={base.action}")
    if proposed * side < -1e-9:
        return _decision(amount=current, action="WAIT_ALLOWED_SIDE",
                         reason=clock_note + "; opposite 1m entry is suppressed",
                         observation=observation, base=base)
    if current and proposed == 0.0:
        return _decision(amount=current, action="HOLD_SLOW_EXIT",
                         reason=clock_note + "; entry-clock flatten deferred to exit MACD",
                         observation=observation, base=base)
    # V2.1's own two-closed-bar entry and accelerating BUILD rules unchanged.
    if proposed * side > current * side + 1e-9:
        return _decision(amount=proposed, action=base.action,
                         reason=clock_note + "; " + base.reason,
                         observation=observation, base=base)
    return _decision(amount=current, action="HOLD",
                     reason=clock_note + "; " + base.reason,
                     observation=observation, base=base)


def long_flat_target_v3(**kwargs):
    return split_target_v3(side=1, **kwargs)


def short_flat_target_v3(**kwargs):
    return split_target_v3(side=-1, **kwargs)


__all__ = [
    "LONG_KEY_V3", "SHORT_KEY_V3", "SPLIT_KEYS_V3",
    "split_target_v3", "long_flat_target_v3", "short_flat_target_v3",
]
