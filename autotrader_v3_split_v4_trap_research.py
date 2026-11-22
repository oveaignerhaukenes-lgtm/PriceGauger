"""Research-only V4: causal, bounded tolerance for recurring countertrend traps.

The V3 strategy stays authoritative for entries, regime changes, missing data,
price shocks and confirmed reversals. Only a *soft* E-MACD exit may be deferred
when the current countertrend leg closely matches completed earlier legs.
There is no broker API, mutable learning state or LIVE strategy registration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from statistics import median

from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _decision, _utc
from autotrader_v3_macd_stoch_v21_split_v2 import price_exit_evidence_v2
from autotrader_v3_macd_stoch_v21_split_v3 import split_price_hist_regime_v3


SOFT_EXIT_ACTIONS = frozenset({"PRICE_CONFIRMED_EXIT_FLAT", "HISTOGRAM_EXHAUSTION_FLAT"})


@dataclass(frozen=True, slots=True)
class TrapProfileV4:
    prior_count: int
    median_depth: float
    median_minutes: float
    active_depth: float
    active_minutes: int
    atr_points: float
    trend_progress: float
    repeatable: bool
    within_tolerance: bool


def trap_profile_v4(*, source_bars, cutoff, market_name: str, side: int) -> TrapProfileV4 | None:
    """Find fully *recovered* close-to-close pullbacks before the current one.

    The current leg cannot train its own tolerance. Completed 1m bars only;
    closed-market gaps invalidate the pattern; no interpolation or future bars.
    """
    if side not in (-1, 1):
        raise ValueError("side must be +1 or -1")
    bars = _completed_bars(source_bars, timeframe=1, cutoff=cutoff, market=market_name)
    if len(bars) < 51:
        return None
    recent = bars[-51:]
    if any(_utc(b.bar_time) - _utc(a.bar_time) != timedelta(minutes=1)
           for a, b in zip(recent, recent[1:])):
        return None
    evidence = price_exit_evidence_v2(
        source_bars=source_bars, cutoff=cutoff, market_name=market_name, side=side)
    if evidence is None or not isfinite(evidence.atr_points) or evidence.atr_points <= 0:
        return None
    signed_closes = [side * float(bar.close) for bar in recent]
    complete = []
    peak = signed_closes[0]
    pullback_start = None
    maximum_depth = 0.0
    for index, signed_close in enumerate(signed_closes[1:], start=1):
        if signed_close >= peak:
            # A partial positive bounce is NOT a completed trap: it must
            # reclaim the signed closing high that preceded the drawdown.
            if pullback_start is not None:
                complete.append((maximum_depth, index - pullback_start))
                pullback_start = None
                maximum_depth = 0.0
            peak = signed_close
        else:
            if pullback_start is None:
                pullback_start = index - 1
            maximum_depth = max(maximum_depth, peak - signed_close)
    depth = maximum_depth if pullback_start is not None else 0.0
    minutes = (len(recent) - 1 - pullback_start
               if pullback_start is not None else 0)
    prior = complete[-5:]
    if len(prior) < 2:
        return TrapProfileV4(len(prior), 0, 0, depth, minutes,
                             evidence.atr_points, 0, False, False)
    depths = [x[0] for x in prior]
    durations = [x[1] for x in prior]
    typical = median(depths)
    typical_minutes = median(durations)
    # Compare the trend *before* the active adverse leg, not the dip itself.
    before = max(0, len(recent) - 1 - minutes)
    progress = signed_closes[before] - signed_closes[-41]
    stable = (min(depths) >= .4 * typical and max(depths) <= 2 * typical)
    trend = progress >= .6 * evidence.atr_points
    repeatable = bool(stable and trend and minutes > 0)
    # Limit dynamic tolerance even if old excursions were enormous.
    depth_limit = min(1.35 * evidence.atr_points,
                      max(.8 * evidence.atr_points, 1.3 * typical))
    duration_limit = min(5., max(2., 1.5 * typical_minutes))
    within = (repeatable and depth <= depth_limit and
              minutes <= duration_limit)
    return TrapProfileV4(len(prior), typical, typical_minutes, depth, minutes,
                         evidence.atr_points, progress, repeatable, within)


def split_trap_exit_research_v4(*, side: int, current_target, observation,
                                source_bars=(), market_name="", **kwargs):
    """Hold through a recurrent *soft* reversal; never override hard V3 exits.

    A subsequent V3 OPEN is naturally permitted when its original signals
    return. The initial research version does not speculate on early re-entry.
    """
    original = split_price_hist_regime_v3(
        side=side, current_target=current_target, observation=observation,
        source_bars=source_bars, market_name=market_name, **kwargs)
    if not side * float(current_target.amount) > 0:
        return original
    if original.action not in SOFT_EXIT_ACTIONS or float(original.target.amount) != 0:
        return original
    cutoff = getattr(observation, "closed_at", observation.bar_time)
    profile = trap_profile_v4(source_bars=source_bars, cutoff=cutoff,
                              market_name=market_name, side=side)
    if profile is None or not profile.within_tolerance:
        return original
    return _decision(
        amount=current_target.amount, action="V4_REPEATED_TRAP_HOLD",
        reason=(f"Soft V3 exit deferred: adverse={profile.active_depth:.1f}pts/"
                f"{profile.active_minutes}m versus prior median "
                f"{profile.median_depth:.1f}pts/{profile.median_minutes:.0f}m; "
                f"ATR={profile.atr_points:.1f}"),
        observation=observation, base=original,
    )


def long_flat_trap_research_v4(**kwargs):
    return split_trap_exit_research_v4(side=1, **kwargs)


def short_flat_trap_research_v4(**kwargs):
    return split_trap_exit_research_v4(side=-1, **kwargs)
