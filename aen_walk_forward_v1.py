"""AEn walk-forward research: choose on TRAIN, report untouched TEST.

Broker-free and database-free. Frozen one-unit cost-adjusted strategies; this
does NOT authorize changing any forward PAPER cohort or LIVE strategy.
The holdout period MUST NOT contribute to the strategy selection score.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Sequence

from aen_replay_v1 import (
    AEnPaperConfig, FAMILIES, TIMEFRAMES, replay, utc,
    prepare_replay_inputs,
)

CANDIDATE_TIMES = (2, 5, 10)
WALK_VERSION = "aen-walkforward-v1"


@dataclass(frozen=True)
class WalkForwardCandidate:
    name: str
    family: str
    signal_minutes: int
    adaptive: bool
    training_net_pct: float
    training_drawdown_pct: float
    training_executions: int
    holdout_net_pct: float
    holdout_drawdown_pct: float
    holdout_executions: int
    holdout_cost_pct: float
    selected_on_training: bool


@dataclass(frozen=True)
class WalkForwardReport:
    version: str
    start_utc: str
    split_utc: str
    end_utc: str
    train_bars: int
    test_bars: int
    selected_name: str | None
    status: str
    candidates: tuple[WalkForwardCandidate, ...]


def candidate_configs(*, structure_minutes=5, unit_exposure=.2,
                      commission_side_bps=8, quoted_spread_bps=1):
    """Same one-unit sizing, fee and swing period for all 13 candidates."""
    common=dict(
        structure_minutes=structure_minutes, max_units=1,
        unit_exposure=unit_exposure, costs_enabled=True,
        commission_side_bps=commission_side_bps,
        quoted_spread_bps=quoted_spread_bps,
    )
    result=tuple(AEnPaperConfig(family=family,minutes=minutes,**common)
                 for family in FAMILIES for minutes in CANDIDATE_TIMES)
    return result+(AEnPaperConfig(
        family="MACD Hold",minutes=10,adaptive=True,dwell_minutes=20,
        **common),)


def evaluate_walk_forward(bars: Sequence, *, started_at, split_at, ended_at,
                          configs: Sequence[AEnPaperConfig] | None=None,
                          min_train_executions: int=2,
                          min_train_bars=240, min_holdout_bars=120):
    """Single chronological train->test split, with no data-dependent split.

    Train replay inputs stop at split. The holdout uses full data only for
    _causal_ indicator warmup; no position carries across evaluation periods.
    Only the training scores determine the selected strategy.
    """
    start,split,end=map(utc,(started_at,split_at,ended_at))
    if not start < split < end:
        raise ValueError("walk-forward requires start < split < end")
    if min_train_executions < 1 or min_train_bars < 1 or min_holdout_bars < 1:
        raise ValueError("invalid walk-forward eligibility threshold")
    candidates=tuple(configs if configs is not None else candidate_configs())
    if not candidates:
        raise ValueError("no walk-forward candidates")
    structure_keys={(c.structure_minutes,c.pivot_left,c.pivot_right)
                    for c in candidates}
    if len(structure_keys)!=1:
        raise ValueError("all walk-forward candidates need the same structure parameters")
    # Frozen size and cost assumptions; explicit comparison parity.
    assumptions={(c.unit_exposure,c.max_units,c.costs_enabled,
                  c.commission_side_bps,c.quoted_spread_bps)
                 for c in candidates}
    if len(assumptions)!=1 or any(c.max_units!=1 or not c.costs_enabled
                                 for c in candidates):
        raise ValueError("only matched, fee-inclusive one-unit candidates allowed")

    eligible=tuple(sorted((b for b in bars if utc(b.bar_time)<end),
                          key=lambda b:utc(b.bar_time)))
    train_input=tuple(b for b in eligible if utc(b.bar_time)<split)
    train_bars=sum(start<=utc(b.bar_time)<split for b in train_input)
    test_bars=sum(split<=utc(b.bar_time)<end for b in eligible)
    if train_bars < min_train_bars or test_bars < min_holdout_bars:
        return WalkForwardReport(WALK_VERSION,start.isoformat(),split.isoformat(),
             end.isoformat(),train_bars,test_bars,None,"INSUFFICIENT_BARS",())

    train_prepared=prepare_replay_inputs(train_input,candidates[0])
    test_prepared=prepare_replay_inputs(eligible,candidates[0])
    train_reports=[replay(c,train_input,started_at=start,prepared=train_prepared)
                   for c in candidates]
    # Selection is performed BEFORE any holdout result is calculated.
    permitted=[i for i,x in enumerate(train_reports)
               if x.executions>=min_train_executions and x.return_pct>0]
    choice=(max(permitted,key=lambda i:(train_reports[i].return_pct,
                 -train_reports[i].max_drawdown_pct,
                 -train_reports[i].turnover_units,
                 -i)) if permitted else None)
    test_reports=[replay(c,eligible,started_at=split,prepared=test_prepared)
                  for c in candidates]
    rows=[]
    for i,(cfg,train,test) in enumerate(zip(candidates,train_reports,test_reports)):
        rows.append(WalkForwardCandidate(
            name=cfg.label,family=cfg.family,signal_minutes=cfg.minutes,
            adaptive=cfg.adaptive,
            training_net_pct=train.return_pct,
            training_drawdown_pct=train.max_drawdown_pct,
            training_executions=train.executions,
            holdout_net_pct=test.return_pct,
            holdout_drawdown_pct=test.max_drawdown_pct,
            holdout_executions=test.executions,
            holdout_cost_pct=test.total_cost_pct,
            selected_on_training=i==choice))
    return WalkForwardReport(
        WALK_VERSION,start.isoformat(),split.isoformat(),end.isoformat(),
        train_bars,test_bars,
        rows[choice].name if choice is not None else None,
        ("SCORED" if choice is not None else
         "INSUFFICIENT_TRADES" if not any(
            x.executions>=min_train_executions for x in train_reports
         ) else "NO_POSITIVE_TRAIN_EDGE"),
        tuple(rows),
    )
