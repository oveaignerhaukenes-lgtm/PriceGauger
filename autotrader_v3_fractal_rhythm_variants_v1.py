"""SIM-only Fraktal-adaptive variants of two frozen rhythmic V3 baselines.

The underlying Fraktal#1 engine changes only the eligible OPEN/BUILD cadence;
baseline FLAT/REDUCE and all Saxo account limits retain priority. No order
placement, retroactive pivot decisions or broker calls.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import timedelta

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_rhythm_build_v1 import (
    macd_stoch_rhythm_build_target_v3,
)
from autotrader_v3_rhythm_trend_v1 import rhythm_trend_target_v3
from autotrader_v3_fractal_cadence_v1 import (
    fractal_cadence_v1,cadence_interval_minutes_v1,
)

RHYTHM_BUILD_FRACTAL_KEY_V3="macd-stoch-rhythm-build-fractal-v1"
RHYTHM_TREND_FRACTAL_KEY_V3="rhythm-trend-fractal-v1"


def _as_of(observation):
    """MacdObservationV2.bar_time is the *start* of the 1m candle."""
    return getattr(observation, "closed_at",
                   observation.bar_time+timedelta(minutes=1))


def _adapt(*, base, current_target, snapshot, strategy, observation):
    current=float(current_target.amount)
    target=float(base.target.amount)
    # Preserve exits/trim/hold exactly: fractal never postpones risk reduction.
    if target==0.0 or abs(target)<abs(current)-1e-9 or (
            target*current<0 and abs(current)>0):
        return base
    if abs(target)<=abs(current)+1e-9:
        return base
    interval=cadence_interval_minutes_v1(snapshot.level,strategy=strategy)
    if interval is None:
        # Missing fractal context: never open/add; legacy reductions still pass.
        return replace(base,target=TargetInventoryV3(current),
                       action="FRACTAL_WAIT_EVIDENCE",
                       reason=base.reason+"; Fraktal tempo: "+snapshot.reason+
                              "; no new exposure")
    cutoff=_as_of(observation)
    minute_of_day=int(cutoff.hour)*60+int(cutoff.minute)
    if minute_of_day%interval:
        return replace(base,target=TargetInventoryV3(current),
                       action="FRACTAL_WAIT_CADENCE",
                       reason=base.reason+"; Fraktal tempo: "+snapshot.reason+
                              f"; build slot every {interval}m")
    return replace(base,reason=base.reason+
                   "; Fraktal tempo: "+snapshot.reason+
                   f"; approved cadence slot {interval}m")


def rhythm_build_fractal_target_v3(
    *, current_target, observation, previous_observation=None,
    bars=(),source_bars=(),config=None,**_unused,
):
    from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
    base=macd_stoch_rhythm_build_target_v3(
        current_target=current_target,observation=observation,
        previous_observation=previous_observation,bars=bars,
        config=config or MacdTrailingConfigV3(),
    )
    # Reuse Fraktal#1's canonical 1m data, not a recreated "fractal"
    # invented from hindsight swing pivots.
    cadence=fractal_cadence_v1(source_bars,closed_at=_as_of(observation))
    return _adapt(base=base,current_target=current_target,snapshot=cadence,
                  strategy="build",observation=observation)


def rhythm_trend_fractal_target_v3(
    *, current_target,observation,previous_observation=None,bars=(),
    source_bars=(),regime_timeframe_minutes=15,market_name="",config=None,
):
    from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
    base=rhythm_trend_target_v3(
        current_target=current_target,observation=observation,
        previous_observation=previous_observation,bars=bars,
        source_bars=source_bars,regime_timeframe_minutes=regime_timeframe_minutes,
        market_name=market_name,config=config or MacdHistogramConfigV3(),
    )
    cadence=fractal_cadence_v1(source_bars,closed_at=_as_of(observation))
    return _adapt(base=base,current_target=current_target,snapshot=cadence,
                  strategy="trend",observation=observation)


__all__=["RHYTHM_BUILD_FRACTAL_KEY_V3","RHYTHM_TREND_FRACTAL_KEY_V3",
         "rhythm_build_fractal_target_v3","rhythm_trend_fractal_target_v3"]
