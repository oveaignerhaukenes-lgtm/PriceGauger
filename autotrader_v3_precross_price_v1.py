"""PreCross#1 and Histogram+Price: causal 2m MACD + completed 1m price.

Both are purely mechanical and use only already-closed canonical OHLC.
There is no 10/30-second feed, model, broker call, or direct order here.
The normal V3 executor owns FLAT-first reversals and Saxo constraints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3, MacdHistogramDecisionV3,
)
from autotrader_v3_aen2_sticky_regime_v1 import _observations_v3
from autotrader_v3_rhythm_trend_v1 import complete_buckets_v1

PRECROSS_KEY_V3="precross-price-1m-macd2m-v1"
HIST_PRICE_KEY_V3="histogram-price-1m-macd2m-v1"
SIGNAL_MINUTES=1
MACD_MINUTES=2
PRICE_BODY_RANGE_RATIO=.35
MIN_BODY_PCT=.00015
HIST_SLOPE_FRACTION=.10


def _utc(value) -> datetime:
    d=(value if isinstance(value,datetime) else
       datetime.fromisoformat(str(value).replace("Z","+00:00")))
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _evidence(*, observation, bars: Sequence, source_bars: Sequence,
              market_name: str):
    """Latest 1m price and last fully completed 2m MACD, with no lookahead."""
    cutoff=_utc(getattr(observation,"closed_at",
                        _utc(observation.bar_time)+timedelta(minutes=1)))
    if cutoff.second or cutoff.microsecond:
        return None
    if len(bars)<5:
        return None
    price=tuple(b for b in bars if _utc(b.bar_time)<cutoff)[-5:]
    if len(price)!=5:
        return None
    if [_utc(b.bar_time) for b in price] != [
        cutoff-timedelta(minutes=i) for i in (5,4,3,2,1)
    ]:
        return None
    try:
        values=tuple(
            (float(b.open),float(b.high),float(b.low),float(b.close))
            for b in price
        )
        if any(not all(isfinite(v) and v>0 for v in row)
               or row[2]>min(row[0],row[3])
               or row[1]<max(row[0],row[3])
               for row in values):
            return None
    except (TypeError,ValueError,AttributeError):
        return None

    # Complete 2m aggregate buckets enforce no interpolation/gaps.
    if not complete_buckets_v1(source_bars[-420:],cutoff,MACD_MINUTES,3):
        return None
    history=_observations_v3(
        source_bars=source_bars[-420:],closed_at=cutoff,
        timeframe_minutes=MACD_MINUTES,market_name=market_name)
    if len(history)<10:
        return None
    last=history[-1]
    if not 0 <= (cutoff-_utc(last.closed_at)).total_seconds()<=60:
        return None
    histogram=[float(obs.spread) for obs in history[-10:]]
    if not all(isfinite(h) for h in histogram):
        return None
    delta=histogram[-1]-histogram[-2]
    past_changes=[abs(histogram[i]-histogram[i-1])
                  for i in range(1,len(histogram)-1)]
    median_delta=median(past_changes)
    # The floor prevents exact parallel/noise bars from becoming a direction.
    slope_floor=max(1e-10,median_delta*HIST_SLOPE_FRACTION)
    op,hi,lo,cl=values[-1]
    body=cl-op
    past=values[-4:-1]
    typical_range=median(row[1]-row[2] for row in values[:-1])
    meaningful=abs(body)>=max(typical_range*PRICE_BODY_RANGE_RATIO,
                              cl*MIN_BODY_PCT)
    up_break=meaningful and body>0 and cl>max(row[1] for row in past)
    down_break=meaningful and body<0 and cl<min(row[2] for row in past)
    close_list=[row[3] for row in values]
    up_sequence=(close_list[-1]>close_list[-2]>close_list[-3]
                 and body>0 and meaningful)
    down_sequence=(close_list[-1]<close_list[-2]<close_list[-3]
                   and body<0 and meaningful)
    return {
        "hist":histogram[-1],"previous":histogram[-2],
        "delta":delta,"floor":slope_floor,
        "up_break":up_break,"down_break":down_break,
        "up_sequence":up_sequence,"down_sequence":down_sequence,
        "last_price_change":cl-close_list[-2],
        "cutoff":cutoff,
    }


def _decide(*, variant: str, current_target: TargetInventoryV3,
            observation, bars: Sequence, source_bars: Sequence,
            market_name: str, config: MacdHistogramConfigV3):
    current=float(current_target.amount)
    h=float(observation.spread)
    tranche=float(config.tranche)

    def emit(amount: float, action: str, explanation: str):
        value=TargetInventoryV3(round(float(amount),10))
        if abs(value.amount)>min(tranche,float(config.max_inventory))+1e-9:
            raise ValueError("one legal tranche ceiling exceeded")
        return MacdHistogramDecisionV3(
            value,action,f"{variant}: {explanation}",h)

    proof=_evidence(observation=observation,bars=bars,
                    source_bars=source_bars,market_name=market_name)
    if proof is None:
        # Fail-closed on invalid/missing history. No strategy target opens.
        return emit(0.,"FLAT_NO_EVIDENCE",
                    "missing contiguous closed 1m OHLC or confirmed 2m MACD")
    delta=proof["delta"]
    threshold=proof["floor"]
    side=1 if delta>threshold else -1 if delta < -threshold else 0
    if variant=="PreCross#1":
        # Histogram SLOPE may turn while histogram LEVEL still has old sign.
        confirmed=(side==1 and proof["up_break"] or
                   side==-1 and proof["down_break"])
    else:
        confirmed=(side==1 and proof["up_sequence"] or
                   side==-1 and proof["down_sequence"])

    context=(f"2m hist {proof['previous']:+.5f}->{proof['hist']:+.5f}"
             f" Δ={delta:+.5f} threshold={threshold:.5f}; "
             f"1m price confirmed={confirmed}")

    if current:
        holding_side=1 if current>0 else -1
        # Flat BEFORE any adverse cross, including strong opposite price
        # breakout while the MACD lines have not yet crossed.
        if holding_side*side<=0:
            return emit(0.,"FLAT_CONTRACTION",
                        f"MACD momentum parallel/contracting against inventory; {context}")
        # Strong price opposition is a separate early exit authority.
        opposite_break=(holding_side==1 and proof["down_break"] or
                        holding_side==-1 and proof["up_break"])
        if opposite_break:
            return emit(0.,"FLAT_PRICE",
                        f"opposite 1m breakout; {context}")
        return emit(holding_side*tranche,"HOLD",
                    f"same-side histogram continues; {context}")

    if side==0:
        return emit(0.,"FLAT_PARALLEL",
                    f"MACD lines nearly parallel; {context}")
    if not confirmed:
        return emit(0.,"WAIT_PRICE",
                    f"momentum without {variant} price confirmation; {context}")
    direction="LONG" if side==1 else "SHORT"
    pre_cross=(side==1 and proof["hist"]<0 or
               side==-1 and proof["hist"]>0)
    return emit(side*tranche,"OPEN",
                f"{direction} at confirmed 1m price move; "
                f"{'BEFORE' if pre_cross else 'AFTER'} 2m MACD zero-cross; "
                f"{context}")


def precross_price_target_v3(
    *,current_target: TargetInventoryV3,observation,
    previous_observation=None,bars:Sequence=(),source_bars:Sequence=(),
    market_name:str="",config:MacdHistogramConfigV3=MacdHistogramConfigV3()
):
    del previous_observation
    return _decide(variant="PreCross#1",current_target=current_target,
                   observation=observation,bars=bars,source_bars=source_bars,
                   market_name=market_name,config=config)


def histogram_price_target_v3(
    *,current_target: TargetInventoryV3,observation,
    previous_observation=None,bars:Sequence=(),source_bars:Sequence=(),
    market_name:str="",config:MacdHistogramConfigV3=MacdHistogramConfigV3()
):
    del previous_observation
    return _decide(variant="Histogram+Price",current_target=current_target,
                   observation=observation,bars=bars,source_bars=source_bars,
                   market_name=market_name,config=config)


__all__=[
    "PRECROSS_KEY_V3","HIST_PRICE_KEY_V3",
    "precross_price_target_v3","histogram_price_target_v3",
]
