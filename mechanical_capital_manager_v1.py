"""Mechanical 15-minute capital allocator using independent shadow equity.

PAPER ONLY: no Saxo calls, broker writes, changes to V3 execution policy,
account ownership, arming, strategy controls or worker. An observed account
NAV is NOT a shadow strategy return; callers must supply independent,
cost-aware, causally marked strategy trajectories which continue at weight 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from typing import Sequence

SLOT_MINUTES = 15
MAX_MODELS = 4
MAX_OBSERVATIONS = 5000
STOP_DRAWDOWN_PCT = 10.0
DECREASE_PP_PER_LOSS_PCT = 10.0
REENTRY_FRACTION = 0.10
RECOVERY_POSITIVE_SLOTS = 2


@dataclass(frozen=True, slots=True)
class ObserverPoint:
    at: datetime
    shadow_equity: float


@dataclass(frozen=True, slots=True)
class StrategyObserver:
    instance_id: str
    strategy_key: str
    currency: str
    manual_slider_pct: float
    points: tuple[ObserverPoint, ...]
    independent_of_allocation: bool = True
    execution_mode: str = "PAPER"


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    at: datetime
    instance_id: str
    strategy_key: str
    shadow_return_15m_pct: float
    shadow_drawdown_pct: float
    cap_pct: float
    suggested_exposure_pct: float
    state: str
    detail: str


@dataclass(frozen=True, slots=True)
class AllocationReplay:
    evaluated_slots: int
    decisions: tuple[AllocationDecision, ...]
    portfolio_equity: tuple[tuple[datetime, float], ...]
    fixed_equity: tuple[tuple[datetime, float], ...]
    correlations: tuple[tuple[str, str, float], ...]
    status: str
    notes: tuple[str, ...]


def _utc(value) -> datetime:
    parsed = (value if isinstance(value, datetime)
              else datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware UTC is required")
    return parsed.astimezone(timezone.utc)


def _validate(streams: Sequence[StrategyObserver]) -> tuple[StrategyObserver, ...]:
    models = tuple(streams)
    if not 1 <= len(models) <= MAX_MODELS:
        raise ValueError("select one to four independent observers")
    if len({x.instance_id for x in models}) != len(models):
        raise ValueError("duplicate V3 instance observer")
    if len({(x.instance_id, x.strategy_key) for x in models}) != len(models):
        raise ValueError("duplicate shadow strategy identity")
    if len({x.currency for x in models}) != 1:
        raise ValueError("cannot mix account currencies without FX")
    for s in models:
        if (not s.instance_id or not s.strategy_key or not s.currency
                or not s.independent_of_allocation or s.execution_mode != "PAPER"):
            raise ValueError("verified independent PAPER shadow is required")
        if not isfinite(s.manual_slider_pct) or not 0 <= s.manual_slider_pct <= 100:
            raise ValueError("manual exposure cap must be 0..100")
        if len(s.points) > MAX_OBSERVATIONS:
            raise ValueError("shadow history exceeds bounded lookback")
        last = None
        for x in s.points:
            t = _utc(x.at)
            if (t.second or t.microsecond or t.minute % SLOT_MINUTES
                    or not isfinite(x.shadow_equity) or x.shadow_equity <= 0):
                raise ValueError("strict positive finite 15m-aligned independent equity required")
            if last is not None and t <= last:
                raise ValueError("shadow equity must be ordered and unique")
            last = t
    return models


def _correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 8 or len(a) != len(b):
        return None
    am = sum(a) / len(a)
    bm = sum(b) / len(b)
    av = sum((v-am)**2 for v in a)
    bv = sum((v-bm)**2 for v in b)
    if av <= 1e-12 or bv <= 1e-12:
        return None
    return sum((x-am)*(y-bm) for x,y in zip(a,b)) / sqrt(av*bv)


def replay_mechanical_allocator(
    observers: Sequence[StrategyObserver], *,
    initial_fraction: float = .50,
    turnover_cost_bps: float = 0.0,
) -> AllocationReplay:
    """At t choose allocation with *past* shadow returns; apply to t→t+15m.

    The fraction changes by 10 percentage points of the manual cap per 1%
    realized 15m shadow result; at -10% shadow drawdown from the current risk
    anchor it latches at 0. Two green independent shadow slots plus positive
    60m shadow return are needed to probe reentry at 10% of manual cap.

    This is a non-deployed mechanical rule, NOT any guarantee of max loss.
    """
    models = _validate(observers)
    if not isfinite(initial_fraction) or not 0 < initial_fraction <= 1:
        raise ValueError("initial_fraction out of range")
    if not isfinite(turnover_cost_bps) or not 0 <= turnover_cost_bps <= 100:
        raise ValueError("turnover cost invalid")
    sample_maps = [
        {_utc(x.at): x.shadow_equity for x in s.points}
        for s in models
    ]
    clock = sorted(set.intersection(*(set(s) for s in sample_maps)))
    if len(clock) < 6:
        return AllocationReplay(
            0, (), (), (), (), "INSUFFICIENT_COMMON_HISTORY",
            ("Need >=6 common 15-minute snapshots from every chosen strategy.",)
        )
    fraction = [m.manual_slider_pct * initial_fraction for m in models]
    peaks = [sample_maps[i][clock[0]] for i in range(len(models))]
    stops = [False]*len(models)
    green_streak = [0]*len(models)
    decisions = []
    nav = fixed_nav = 1.0
    curve = [(clock[0], nav)]
    fixed_curve = [(clock[0], fixed_nav)]
    increments = [[] for _ in models]
    observed = 0
    last = clock[0]
    for at in clock[1:]:
        if at - last != timedelta(minutes=SLOT_MINUTES):
            # Unknown return during gap: don't bridge, clear allocation
            # and reset observation peak only after complete resumed data.
            fraction = [0.]*len(models)
            stops = [True]*len(models)
            peaks = [sample_maps[i][at] for i in range(len(models))]
            green_streak = [0]*len(models)
            for i, m in enumerate(models):
                decisions.append(AllocationDecision(
                    at, m.instance_id, m.strategy_key, 0., 0.,
                    m.manual_slider_pct, 0., "GAP_PAUSE",
                    "Missing 15m common shadow slot; no inferred outcome or reentry"
                ))
            last = at
            continue
        returns = [
            (sample_maps[i][at]/sample_maps[i][last] - 1.) * 100
            for i in range(len(models))
        ]
        # Capital exposed during this last interval was the allocation from
        # prior decision, not the allocation computed with the new return.
        applied = sum(
            (fraction[i]/100.) * (returns[i]/100.)
            for i in range(len(models))
        ) / len(models)
        static = sum(
            (m.manual_slider_pct/100.) * (returns[i]/100.)
            for i,m in enumerate(models)
        ) / len(models)
        nav = max(0., nav * (1.+applied))
        fixed_nav = max(0., fixed_nav * (1.+static))
        curve.append((at, nav))
        fixed_curve.append((at, fixed_nav))
        observed += 1
        for i,m in enumerate(models):
            increments[i].append(returns[i])
            current = sample_maps[i][at]
            peaks[i] = max(peaks[i], current)
            dd = 100.*(current/peaks[i]-1.)
            if stops[i]:
                green_streak[i] = (green_streak[i]+1) if returns[i] > 0 else 0
                before = at-timedelta(minutes=60)
                four_ago = sample_maps[i].get(before)
                recovery = (four_ago is not None
                            and current > four_ago and green_streak[i] >= RECOVERY_POSITIVE_SLOTS)
                if recovery:
                    stops[i] = False
                    peaks[i] = current   # start a NEW monitored exposure epoch
                    fraction[i] = min(m.manual_slider_pct, m.manual_slider_pct*REENTRY_FRACTION)
                    state, detail = ("PAPER_REENTRY",
                        "Shadow green twice and positive last 60m; restart at 10% of manual cap")
                else:
                    fraction[i] = 0.
                    state, detail = "SHADOW_WAIT", "Zero exposure; independent shadow still monitored"
            elif dd <= -STOP_DRAWDOWN_PCT:
                stops[i] = True
                green_streak[i] = 0
                fraction[i] = 0.
                state,detail="SHADOW_STOP","Shadow peak drawdown exceeded 10%; PAPER target zero"
            else:
                prior_fraction = fraction[i]
                change = (DECREASE_PP_PER_LOSS_PCT
                          * (m.manual_slider_pct/100.) * returns[i])
                fraction[i] = max(0., min(m.manual_slider_pct, prior_fraction+change))
                if fraction[i] == 0:
                    stops[i] = True
                    green_streak[i] = 0
                    state, detail="SHADOW_ZERO","Continuous loss reduced PAPER exposure to zero"
                else:
                    state,detail="PAPER_ADJUST","+/-10 points of manual cap per 1% 15m shadow return"
                # Turnover is a separate hypothetical cost on allocated
                # capital fractions, not simulated broker execution.
                change_frac = abs(prior_fraction-fraction[i])/100.
                nav *= max(0., 1. - change_frac*turnover_cost_bps/10000./len(models))
                curve[-1] = (at, nav)
            decisions.append(AllocationDecision(
                at,m.instance_id,m.strategy_key,returns[i],dd,
                m.manual_slider_pct,round(fraction[i],6),state,detail
            ))
        last = at
    correlations = []
    for i in range(len(models)):
        for j in range(i+1,len(models)):
            corr = _correlation(increments[i],increments[j])
            if corr is not None:
                correlations.append((models[i].strategy_key,
                                     models[j].strategy_key,round(corr,4)))
    notes = (
        "15m PAPER allocation; no LIVE slider/broker writes or automatic liquidations.",
        "Observer returns are independent of exposure, so PAPER shadow can recover from allocation zero.",
        "10% drawdown stop is sampled; instantaneous gap/leveraged losses can exceed it.",
        "No verified NAV/cashflow/performance claim from Saxo balances or opening P/L.",
        "Portfolio results are scenario projections based on input shadow returns, not actual trade fills.",
        "Real allocation requires lot quantization, minimum margin and existing position reduction safeguards.",
    )
    return AllocationReplay(
        observed,tuple(decisions),tuple(curve),tuple(fixed_curve),
        tuple(correlations),"PAPER_ONLY",notes
    )
