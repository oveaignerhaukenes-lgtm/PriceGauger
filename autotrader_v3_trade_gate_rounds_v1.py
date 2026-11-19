"""Compare three predeclared PAPER eligibility rules with actual FLAT replays.

Training outcomes are baseline PAPER NAV changes, NOT real Saxo fills. Each
rule is frozen before the chronological holdout; no selection on test results.
The optional replay gate has no LIVE connection or authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor, sqrt
from statistics import mean, stdev
from typing import Sequence

from autotrader_v3_trade_gate_research_v1 import (
    GateWindow, evaluate_trade_gate_train_holdout,
)
from strategy_lab_v2_replay import ReplayCostsV2, ReplayResultV2, replay_v3_strategy_v2


@dataclass(frozen=True)
class EligibilityRound:
    name: str
    description: str
    decisions: tuple[tuple[str, str, int, float], ...]
    eligible_windows: int
    blocked_windows: int
    holdout_baseline_nok: float
    holdout_gated_nok: float
    holdout_delta_nok: float
    holdout_baseline_drawdown_pct: float
    holdout_gated_drawdown_pct: float
    baseline_orders: int
    gated_orders: int
    gated_execution_cost_nok: float
    gated_result: ReplayResultV2


def _train_actions(train: Sequence[GateWindow], policy: str):
    by_class: dict[str, list[float]] = {}
    for row in train:
        by_class.setdefault(row.class_key, []).append(row.future_paper_nav_pct)
    decisions = {}
    for category, values in sorted(by_class.items()):
        n, avg = len(values), mean(values)
        if policy == "LOSS_BLACKLIST":
            # Default GO; block only a repeatedly losing shape. The 0.05%
            # cushion is predeclared, not chosen on the holdout.
            stop = n >= 6 and avg < -0.05 and sum(v < 0 for v in values) / n >= 0.6
            action = "SKIP" if stop else "TRADE"
        elif policy == "MEAN_CLASS":
            action = ("TRADE" if avg > 0 else "SKIP") if n >= 4 else "SKIP"
        elif policy == "CONFIDENT_ONLY":
            if n < 8:
                action = "SKIP"
            else:
                standard_error = stdev(values) / sqrt(n) if n > 1 else float("inf")
                action = "TRADE" if avg - standard_error > 0.05 else "SKIP"
        else:
            raise ValueError("Unknown PAPER gate policy")
        decisions[category] = (action, n, avg)
    return decisions


def _at(points, time: datetime) -> float:
    match = next((p for p in points if p.at == time), None)
    if match is None:
        raise ValueError("Missing PAPER NAV at holdout boundary")
    return float(match.nav_nok)


def _drawdown(points, start: datetime, end: datetime) -> float:
    navs = [float(p.nav_nok) for p in points if start <= p.at <= end]
    if not navs:
        raise ValueError("Missing PAPER holdout NAV points")
    peak, worst = navs[0], 0.
    for nav in navs:
        peak = max(peak, nav)
        worst = max(worst, 100 * (peak - nav) / peak)
    return worst


def evaluate_full_flat_replay_rounds(
    *, windows: Sequence[GateWindow], baseline: ReplayResultV2,
    bars: Sequence, strategy_key: str, timeframe: str, costs: ReplayCostsV2,
) -> tuple[EligibilityRound, ...]:
    """Evaluate frozen train-policy against held-out *executed PAPER* returns.

    30m labels may overlap neither holdout nor purge. The replay simulates
    closing and re-entering, including costs, so unlike the V1 skipped-window
    proxy it is meaningful to compare PAPER net NAV. It is still NOT live P/L:
    actual broker latency, slippage, swaps and rejected orders are absent.
    """
    evaluation = evaluate_trade_gate_train_holdout(windows)
    if evaluation is None:
        return ()
    ordered = sorted(windows, key=lambda x: x.decision_at)
    cutoff = evaluation.train_cutoff
    train = [w for w in ordered if w.future_until < cutoff]
    test = [w for w in ordered if w.decision_at >= cutoff]
    if len(train) != evaluation.train_windows or len(test) != evaluation.test_windows:
        raise ValueError("PAPER evaluation split mismatch")
    end = test[-1].future_until
    baseline_nok = _at(baseline.points, end) - _at(baseline.points, cutoff)
    baseline_dd = _drawdown(baseline.points, cutoff, end)
    baseline_orders = sum(cutoff <= e.at < end for e in baseline.events)
    result = []
    names = {
        "LOSS_BLACKLIST": "Runde 1 · bare dokumenterte tapsformer stanses",
        "MEAN_CLASS": "Runde 2 · positivt klassegjennomsnitt kreves",
        "CONFIDENT_ONLY": "Runde 3 · usikkerhetsmargin og minst 8 observasjoner",
    }
    for policy, description in names.items():
        actions = _train_actions(train, policy)
        # Every holdout decision t is built from COMPLETED bars before t.
        # Never inspect w.future_paper_nav_pct when deciding eligibility.
        holdout_classes = {w.decision_at: w.class_key for w in test}

        def may_trade(at: datetime) -> bool:
            if at < cutoff or at >= end:
                return True
            epoch = int(at.timestamp())
            bucket = datetime.fromtimestamp(floor(epoch / 1800) * 1800, tz=timezone.utc)
            category = holdout_classes.get(bucket)
            # Unknown 30m source gaps block new risk. The LOSS_BLACKLIST
            # policy otherwise permits as-yet-unmeasured categories.
            if category is None:
                return False
            default = "TRADE" if policy == "LOSS_BLACKLIST" else "SKIP"
            return actions.get(category, (default, 0, 0.))[0] == "TRADE"

        gated = replay_v3_strategy_v2(
            strategy_key=strategy_key, bars=bars, costs=costs,
            timeframe=timeframe, decision_gate=may_trade,
        )
        gated_nok = _at(gated.points, end) - _at(gated.points, cutoff)
        gated_events = [e for e in gated.events if cutoff <= e.at < end]
        allowed = sum(may_trade(w.decision_at) for w in test)
        result.append(EligibilityRound(
            name=policy, description=description,
            decisions=tuple((k, *v) for k, v in sorted(actions.items())),
            eligible_windows=allowed, blocked_windows=len(test)-allowed,
            holdout_baseline_nok=baseline_nok,
            holdout_gated_nok=gated_nok,
            holdout_delta_nok=gated_nok-baseline_nok,
            holdout_baseline_drawdown_pct=baseline_dd,
            holdout_gated_drawdown_pct=_drawdown(gated.points, cutoff, end),
            baseline_orders=baseline_orders,
            gated_orders=len(gated_events),
            gated_execution_cost_nok=sum(e.cost_nok for e in gated_events),
            gated_result=gated,
        ))
    return tuple(result)
