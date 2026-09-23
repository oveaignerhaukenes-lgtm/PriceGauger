from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3

STRATEGY_KEY_V3 = "macd-histogram-v1"

@dataclass(frozen=True, slots=True)
class MacdHistogramConfigV3:
    tranche: float = 0.01
    max_inventory: float = 0.10
    def __post_init__(self):
        if not isfinite(self.tranche) or self.tranche <= 0: raise ValueError("tranche must be positive")
        if not isfinite(self.max_inventory) or self.max_inventory < self.tranche: raise ValueError("max_inventory must be >= tranche")

@dataclass(frozen=True, slots=True)
class MacdHistogramDecisionV3:
    target: TargetInventoryV3
    action: str
    reason: str
    histogram: float

def _q(v,t):
    x=round(v/t)*t
    return 0.0 if abs(x)<t/2 else x

def macd_histogram_target_v3(*,current_target,observation,previous_observation=None,config=MacdHistogramConfigV3()):
    """Only dependency: MACD histogram value and its bar-to-bar direction."""
    h=float(observation.spread); current=_q(current_target.amount,config.tranche)
    if previous_observation is None:
        delta=config.tranche if h>0 else (-config.tranche if h<0 else 0.0)
    else:
        prev=float(previous_observation.spread)
        # Histogram direction alone controls inventory: rising => one step LONG,
        # falling => one step SHORT. This naturally reduces the old side before
        # crossing and rebuilds it if the histogram turns back.
        delta=config.tranche if h>prev else (-config.tranche if h<prev else 0.0)
    target=_q(max(-config.max_inventory,min(config.max_inventory,current+delta)),config.tranche)
    if target==current: action="HOLD"
    elif abs(target)<abs(current): action="REDUCE"
    elif current==0 or (current>0)==(target>0): action="ADD"
    else: action="CROSS_ZERO"
    return MacdHistogramDecisionV3(TargetInventoryV3(target),action,f"histogram {h:+.6f}; direction-only step {delta:+g}",h)

def replay_macd_histogram_v3(observations: Sequence[MacdObservationV2],*,config=MacdHistogramConfigV3(),initial_target=TargetInventoryV3(0.0)):
    out=[]; target=initial_target; prev=None
    for obs in observations:
        d=macd_histogram_target_v3(current_target=target,observation=obs,previous_observation=prev,config=config)
        out.append(d); target=d.target; prev=obs
    return tuple(out)
