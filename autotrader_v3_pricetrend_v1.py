"""PriceTrend #1: causal Tech100 price-regime strategy (V3 SIM and guarded LIVE).

MACD/Stoch never determine direction here. Completed 1m Saxo OHLC is
aggregated into completed 5m regime and 2m timing candles. Missing/gapped
bars flatten rather than invent continuity. No broker, DB, AI or volume.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3, MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "pricetrend-1-v1"
BASELINE_KEY_V3 = "sma-9-21-2m-baseline-v1"
CATALOG_KEY_V3 = "pricetrend-1"
BASELINE_CATALOG_KEY_V3 = "sma-9-21-baseline"
TECH100_MARKET = "US Tech 100 NAS"

# Initial hypotheses, NOT calibrated or optimized on user's screenshot.
SMA_FAST = 9
SMA_SLOW = 21
ATR_PERIOD = 14
ER_PERIOD = 12
MIN_EFFICIENCY = 0.35
MIN_SLOPE_ATR = 0.08         # 5m SMA21 change over 3 completed bars
MIN_PRICE_DISTANCE_ATR = 0.10
TRAIL_ATR_MULTIPLE = 2.5
TRAIL_LOOKBACK_5M = 12
MIN_HISTORY_1M = 150        # 5m regime warmup, independent of signal period
SUPPORTED_SIGNAL_MINUTES = (1,2,5,10,15,30,60)
TECH100_UIC = 4912
TECH100_ASSET_TYPE = "CfdOnIndex"


@dataclass(frozen=True, slots=True)
class Candle:
    at: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class RegimeEvidence:
    regime: str
    atr: float | None
    er: float | None
    sma21: float | None
    sma9: float | None
    slope_atr: float | None
    price: float | None


def _utc(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if result.tzinfo is None:
        raise ValueError("PriceTrend timestamps require explicit time zone")
    return result.astimezone(timezone.utc)


def _closed_source(source_bars: Sequence, cutoff: datetime,
                   signal_minutes: int=2) -> tuple[Candle, ...]:
    """Accept only contiguous, valid, fully completed 1m candles ending at cutoff."""
    bars = sorted(
        (bar for bar in source_bars if _utc(bar.bar_time) < cutoff),
        key=lambda bar: _utc(bar.bar_time),
    )
    minimum=max(MIN_HISTORY_1M,10*signal_minutes+signal_minutes)
    if len(bars) < minimum:
        raise ValueError("PriceTrend needs more completed 1m bars for chosen S timeframe")
    # Keep more than the 9+1 completed S bars plus the 5m macro warmup.
    # At S=60m retain >= 660 genuine 1m bars, without any extra SQL requests.
    bars = bars[-max(180,12*signal_minutes):]
    result = []
    for bar in bars:
        t = _utc(bar.bar_time)
        vals = tuple(float(getattr(bar, key)) for key in ("open", "high", "low", "close"))
        op, hi, lo, close = vals
        if (t.second or t.microsecond or not all(isfinite(x) and x > 0 for x in vals)
                or not (lo <= op <= hi and lo <= close <= hi)):
            raise ValueError("PriceTrend invalid OHLC")
        if result and t - result[-1].at != timedelta(minutes=1):
            raise ValueError("PriceTrend missing or duplicate canonical bars")
        result.append(Candle(t, op, hi, lo, close))
    if result[-1].at + timedelta(minutes=1) != cutoff:
        raise ValueError("PriceTrend only uses last completed 1m source")
    return tuple(result)


def _aggregate(bars: Sequence[Candle], minutes: int) -> tuple[Candle, ...]:
    """Use aligned COMPLETE higher-timeframe candles; no partial current candle."""
    out = []
    groups: dict[datetime, list[Candle]] = {}
    for bar in bars:
        n = int(bar.at.timestamp())
        start = datetime.fromtimestamp(
            n - n % (60 * minutes), tz=timezone.utc
        )
        groups.setdefault(start, []).append(bar)
    for start, group in sorted(groups.items()):
        if (len(group) != minutes or group[0].at != start or
                group[-1].at != start + timedelta(minutes=minutes-1)):
            continue
        out.append(Candle(start, group[0].open, max(v.high for v in group),
                          min(v.low for v in group), group[-1].close))
    return tuple(out)


def _sma(values: Sequence[float], period: int) -> float:
    return sum(values[-period:]) / period


def _atr(bars: Sequence[Candle], period: int = ATR_PERIOD) -> float:
    ranges = []
    for prev, cur in zip(bars[-period-1:-1], bars[-period:]):
        ranges.append(max(cur.high - cur.low,
                          abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(ranges) / period


def _er(closes: Sequence[float], period: int = ER_PERIOD) -> float:
    lookback = closes[-period-1:]
    path = sum(abs(b-a) for a,b in zip(lookback,lookback[1:]))
    return abs(lookback[-1] - lookback[0])/path if path > 0 else 0.0


def price_regime_v1(bars_5m: Sequence[Candle]) -> RegimeEvidence:
    """Weak price action cannot fake a new trend, but not every pause is FLAT."""
    unknown = RegimeEvidence("UNKNOWN",None,None,None,None,None,None)
    if len(bars_5m) < max(SMA_SLOW + 3, ATR_PERIOD+1, ER_PERIOD+1):
        return unknown
    closes = [bar.close for bar in bars_5m]
    atr = _atr(bars_5m)
    if not isfinite(atr) or atr <= 0:
        return unknown
    sma21 = _sma(closes,21)
    sma9 = _sma(closes,9)
    old_sma21 = _sma(closes[:-3],21)
    slope = (sma21 - old_sma21) / atr
    efficiency = _er(closes)
    price = closes[-1]
    # Robust, completed 5m LH/LL vs prior 3-bar block, rather than demanding
    # every tiny candle extend the trend. This structure filters SMA crossovers.
    prev_block = bars_5m[-6:-3]
    recent_block = bars_5m[-3:]
    lower_high = max(b.high for b in recent_block) <= max(
        b.high for b in prev_block) + 0.15 * atr
    lower_low = min(b.low for b in recent_block) < min(
        b.low for b in prev_block) - 0.15 * atr
    higher_high = max(b.high for b in recent_block) > max(
        b.high for b in prev_block) + 0.15 * atr
    higher_low = min(b.low for b in recent_block) >= min(
        b.low for b in prev_block) - 0.15 * atr
    # ER prevents new exposure to pure noise. Existing exposure is handled
    # separately using direction, 21SMA and ATR trailing protection.
    if efficiency < MIN_EFFICIENCY:
        regime = "SIDEWAYS"
    elif (lower_high and lower_low and slope <= -MIN_SLOPE_ATR and sma9 < sma21 and
          price < sma21 - MIN_PRICE_DISTANCE_ATR * atr):
        regime = "BEAR"
    elif (higher_high and higher_low and slope >= MIN_SLOPE_ATR and sma9 > sma21 and
          price > sma21 + MIN_PRICE_DISTANCE_ATR * atr):
        regime = "BULL"
    else:
        regime = "TRANSITION"
    return RegimeEvidence(regime,atr,efficiency,sma21,sma9,slope,price)


def _decision(current, wanted, action, why, observation):
    return MacdHistogramDecisionV3(
        target=TargetInventoryV3(round(float(wanted),10)),
        action=action,reason=why,
        histogram=float(observation.spread),
    )


def _common(*, current_target, observation, source_bars, config,
            market_name,signal_timeframe_minutes=2):
    current = float(current_target.amount)
    if str(market_name) != TECH100_MARKET:
        return current, None, None, _decision(current,0,"FLAT_OTHER_MARKET",
            "PriceTrend allowed only on canonical US Tech 100 NAS", observation)
    try:
        signal_minutes=int(signal_timeframe_minutes)
        if signal_minutes not in SUPPORTED_SIGNAL_MINUTES:
            raise ValueError("Unsupported PriceTrend signal period")
        closed_at = _utc(observation.closed_at)
        bars_1m = _closed_source(source_bars,closed_at,signal_minutes)
        five = _aggregate(bars_1m,5)
        signal = _aggregate(bars_1m,signal_minutes)
        # Require an actual newly completed signal bar at this decision.
        if (not signal or signal[-1].at + timedelta(minutes=signal_minutes)!=closed_at
                or len(five)<SMA_SLOW+3 or len(signal)<SMA_FAST+1):
            raise ValueError("not enough aligned completed 5m regime and S signal candles")
    except (ValueError, TypeError, AttributeError, OverflowError):
        return current, None, None, _decision(current,0,"FLAT_DATA_GAP",
            "missing/incomplete source; no synthetic candle or stale entry",observation)
    return current, five, signal, None


def pricetrend_target_v1(*,current_target:TargetInventoryV3,
                         observation,previous_observation=None,
                         source_bars:Sequence=(),market_name="",
                         config:MacdHistogramConfigV3=MacdHistogramConfigV3(),
                         signal_timeframe_minutes:int=2, **_):
    """One legal tranche; opposite side requires a separate FLAT decision."""
    current, five, signal, blocked = _common(
        current_target=current_target,observation=observation,
        source_bars=source_bars,config=config,market_name=market_name,
        signal_timeframe_minutes=signal_timeframe_minutes)
    if blocked is not None:
        return blocked
    evidence = price_regime_v1(five)
    # Never add exposure to a broker-confirmed position larger than the
    # chosen one-tranche strategy can manage. Avoid a forced liquidation
    # merely because the previous strategy held multiple tranches.
    if abs(current)>float(config.tranche)+1e-9:
        return _decision(current,current,"HOLD_OVERSIZE",
            "Position exceeds PriceTrend one-tranche LIVE envelope",observation)
    if evidence.regime == "UNKNOWN":
        return _decision(current,0,"FLAT_WARMUP","5m ATR/SMA warmup",observation)
    close = signal[-1].close
    fast = _sma([b.close for b in signal],SMA_FAST)
    old_fast = _sma([b.close for b in signal[:-1]],SMA_FAST)
    atr = evidence.atr
    if current < 0:
        trail = min(b.low for b in five[-TRAIL_LOOKBACK_5M:]) + TRAIL_ATR_MULTIPLE*atr
        if close > trail or close > evidence.sma21 + 0.5*atr or evidence.regime=="BULL":
            return _decision(current,0,"EXIT_SHORT",
                f"price invalidation: last={close:.2f}, trail={trail:.2f}, "
                f"ATR5m={atr:.2f}, regime={evidence.regime}",observation)
        return _decision(current,current,"HOLD_SHORT",
            f"hold price BEAR/pullback: 5m={evidence.regime} ER={evidence.er:.2f} "
            f"SMA21 slope/ATR={evidence.slope_atr:.2f}",observation)
    if current > 0:
        trail = max(b.high for b in five[-TRAIL_LOOKBACK_5M:]) - TRAIL_ATR_MULTIPLE*atr
        if close < trail or close < evidence.sma21 - 0.5*atr or evidence.regime=="BEAR":
            return _decision(current,0,"EXIT_LONG",
                f"price invalidation: last={close:.2f}, trail={trail:.2f}, "
                f"ATR5m={atr:.2f}, regime={evidence.regime}",observation)
        return _decision(current,current,"HOLD_LONG",
            f"hold price BULL/pullback: 5m={evidence.regime} ER={evidence.er:.2f} "
            f"SMA21 slope/ATR={evidence.slope_atr:.2f}",observation)
    if evidence.regime=="BEAR" and close < fast and fast <= old_fast:
        return _decision(current,-config.tranche,"OPEN_SHORT",
            f"5m BEAR+LH/LL ER={evidence.er:.2f} ATR={atr:.2f}; price below S{signal_timeframe_minutes} SMA9",observation)
    if evidence.regime=="BULL" and close > fast and fast >= old_fast:
        return _decision(current,config.tranche,"OPEN_LONG",
            f"5m BULL+HH/HL ER={evidence.er:.2f} ATR={atr:.2f}; price above S{signal_timeframe_minutes} SMA9",observation)
    return _decision(current,0,"WAIT_TREND",
        f"5m {evidence.regime}; awaiting S{signal_timeframe_minutes} continuation",observation)


def sma_9_21_baseline_target_v1(*,current_target:TargetInventoryV3,
                               observation,previous_observation=None,
                               source_bars:Sequence=(),market_name="",
                               config:MacdHistogramConfigV3=MacdHistogramConfigV3(),
                               signal_timeframe_minutes:int=2,**_):
    """Independent 2m SMA9/21 no ATR or ER: explicit comparator, SIM only."""
    if signal_timeframe_minutes!=2:
        return _decision(current,0,"FLAT_BASELINE_TIMEFRAME",
            "SMA research baseline is 2m only",observation)
    current, five, two, blocked = _common(
        current_target=current_target,observation=observation,
        source_bars=source_bars,config=config,market_name=market_name,
        signal_timeframe_minutes=2)
    if blocked is not None:
        return blocked
    vals = [b.close for b in two]
    fast,slow = _sma(vals,9),_sma(vals,21)
    sign = 1 if fast > slow else -1 if fast < slow else 0
    if current and (current*sign <= 0):
        return _decision(current,0,"SMA_EXIT","SMA9/21 sign no longer aligned",observation)
    if current:
        return _decision(current,current,"SMA_HOLD","SMA9/21 regime still aligned",observation)
    wanted = sign*config.tranche
    return _decision(current,wanted,
        "SMA_LONG" if sign>0 else "SMA_SHORT" if sign<0 else "SMA_FLAT",
        "2m SMA9/21 crossing baseline; no ATR/ER confirmation",observation)


__all__ = ["STRATEGY_KEY_V3","BASELINE_KEY_V3","CATALOG_KEY_V3",
           "BASELINE_CATALOG_KEY_V3","price_regime_v1",
           "pricetrend_target_v1","sma_9_21_baseline_target_v1"]
