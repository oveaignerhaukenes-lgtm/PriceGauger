"""Experimental price-confirmed MACD regime with pre-cross histogram recovery.

Separate Long/Flat and Short/Flat V3 strategies. V1/V2 stay unchanged.
Only fully closed 1m and R/E candles are used. A converging (still opposite)
R-MACD histogram is *not* a trading signal by itself: recent prices must
confirm a real structural breakout before pre-cross entry is permitted.
No broker authority, hidden risk stop, automatic account switching or AI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_macd_stoch_v21_split_v1 import (
    ALLOWED_CLOCKS_V3, _completed_bars, _decision, _latest_macd, _utc,
)
from autotrader_v3_macd_stoch_v21_split_v2 import (
    LONG_KEY_V2, SHORT_KEY_V2, SPLIT_V2_KEYS_V3,
    ALL_SPLIT_KEYS_V3 as PREVIOUS_SPLIT_KEYS_V3, price_exit_evidence_v2,
)

LONG_KEY_V3_PRICE_HIST = "macd-stoch-v21-r-long-flat-v3"
SHORT_KEY_V3_PRICE_HIST = "macd-stoch-v21-r-short-flat-v3"
SPLIT_V3_KEYS_V3 = frozenset({LONG_KEY_V3_PRICE_HIST, SHORT_KEY_V3_PRICE_HIST})
ALL_SPLIT_KEYS_V3 = PREVIOUS_SPLIT_KEYS_V3 | SPLIT_V3_KEYS_V3


@dataclass(frozen=True, slots=True)
class RegimeHistogramV3:
    signed_spread: float
    recovering_before_cross: bool
    weakening_before_cross: bool


@dataclass(frozen=True, slots=True)
class PriceConfirmationV3:
    atr_points: float
    signed_5m: float
    signed_2m: float
    aligned: bool
    strong_breakout: bool
    opposite_breakout: bool


def regime_histogram_v3(*, source_bars, cutoff, minutes: int, market_name: str,
                        side: int) -> RegimeHistogramV3 | None:
    """R-MACD spread and 3 completed, contiguous histogram observations.

    The 35-R-bar MACD warmup and freshness contract is the V1/V2 contract.
    A 35% contraction over two completed R bars is an *experimental* cutoff.
    """
    bars = _completed_bars(source_bars, timeframe=minutes,
                           cutoff=cutoff, market=market_name)
    if len(bars) < 35:
        return None
    points = macd_observations_v2(bars, timeframe_minutes=minutes)
    if len(points) < 3:
        return None
    last = points[-3:]
    if (_utc(cutoff) - _utc(last[-1].closed_at) > timedelta(minutes=minutes)
            or any(_utc(b.closed_at) - _utc(a.closed_at) != timedelta(minutes=minutes)
                   for a, b in zip(last, last[1:]))):
        return None
    signed = tuple(side * float(item.spread) for item in last)
    if not all(isfinite(value) for value in signed):
        return None
    a, b, c = signed
    # Histograms can converge without ever crossing. Price is the second,
    # independent gate; convergence alone never triggers OPEN or FLAT.
    recovering = (a < b < c < 0 and abs(c) <= .65 * abs(a))
    weakening = (a > b > c > 0 and c <= .65 * a)
    return RegimeHistogramV3(
        signed_spread=c, recovering_before_cross=recovering,
        weakening_before_cross=weakening,
    )


def price_confirmation_v3(*, source_bars, cutoff, market_name: str,
                          side: int, adverse_evidence=None) -> PriceConfirmationV3 | None:
    """Causal 1m ATR and recent price structure; never use a forming bar."""
    evidence = adverse_evidence
    if evidence is None:
        evidence = price_exit_evidence_v2(
            source_bars=source_bars, cutoff=cutoff,
            market_name=market_name, side=side,
        )
    if evidence is None:
        return None
    bars = _completed_bars(source_bars, timeframe=1,
                           cutoff=cutoff, market=market_name)
    if len(bars) < 18:
        return None
    recent = bars[-18:]
    if any(_utc(b.bar_time) - _utc(a.bar_time) != timedelta(minutes=1)
           for a, b in zip(recent, recent[1:])):
        return None
    atr = evidence.atr_points
    change5 = side * (recent[-1].close - recent[-6].close)
    change2 = side * (recent[-1].close - recent[-3].close)
    prior = recent[-7:-1]
    bullish_breakout = recent[-1].close > max(x.high for x in prior) + .10 * atr
    bearish_breakout = recent[-1].close < min(x.low for x in prior) - .10 * atr
    breakout = bullish_breakout if side > 0 else bearish_breakout
    opposite = bearish_breakout if side > 0 else bullish_breakout
    return PriceConfirmationV3(
        atr_points=atr, signed_5m=change5, signed_2m=change2,
        aligned=(change5 >= .35 * atr and change2 > 0),
        strong_breakout=(breakout and change5 >= 1.25 * atr
                         and change2 >= .25 * atr),
        opposite_breakout=(opposite and change5 <= -1.25 * atr
                           and change2 <= -.25 * atr),
    )


def split_price_hist_regime_v3(*, side: int, current_target: TargetInventoryV3,
        observation, previous_observation=None, bars=(), source_bars=(),
        regime_timeframe_minutes: int=10, exit_timeframe_minutes: int=2,
        market_name: str="", config: MacdTrailingConfigV3=MacdTrailingConfigV3()):
    """A price-confirmed one-sided regime, with an optional pre-cross phase.

    Existing positions are protected by V2's E+adverse-price exit and shock
    exit. A hist+price reversal can flatten *before* the actual R cross.
    Early opens are allowed only when both hist recovery and strong 1m price
    breakout are present; later HOLD may survive a small retracement.
    """
    if side not in (-1, 1):
        raise ValueError("V3 side must be +1 or -1")
    if (int(regime_timeframe_minutes) not in ALLOWED_CLOCKS_V3 or
            int(exit_timeframe_minutes) not in ALLOWED_CLOCKS_V3):
        raise ValueError("Unsupported completed MACD clock")
    cutoff = getattr(observation, "closed_at", observation.bar_time)
    current = float(current_target.amount)
    if side * current < -1e-9:
        return _decision(amount=0, action="WRONG_SIDE_FLAT",
                         reason="Opposite inventory denied", observation=observation)
    regime = regime_histogram_v3(
        source_bars=source_bars, cutoff=cutoff,
        minutes=int(regime_timeframe_minutes), market_name=market_name, side=side,
    )
    exit_macd = _latest_macd(
        source_bars, minutes=int(exit_timeframe_minutes),
        cutoff=cutoff, market=market_name,
    )
    adverse = price_exit_evidence_v2(
        source_bars=source_bars, cutoff=cutoff,
        market_name=market_name, side=side,
    )
    price = price_confirmation_v3(
        source_bars=source_bars, cutoff=cutoff,
        market_name=market_name, side=side, adverse_evidence=adverse,
    )
    if regime is None or exit_macd is None or price is None or adverse is None:
        return _decision(amount=0, action="CLOCK_OR_PRICE_UNAVAILABLE_FLAT",
                         reason="No fresh R/E candles or contiguous 1m price/ATR",
                         observation=observation)

    native_regime = regime.signed_spread > 0
    early_regime = (regime.recovering_before_cross and price.strong_breakout)
    # Protect an early position while recovery still continues: requiring a
    # fresh price breakout every minute would make any normal pause exit.
    early_hold = (current != 0 and regime.recovering_before_cross
                  and price.signed_5m >= -.35 * price.atr_points)
    early_adverse = (native_regime and regime.weakening_before_cross
                     and price.opposite_breakout)
    if early_adverse and current:
        return _decision(amount=0, action="EARLY_REGIME_REVERSAL_FLAT",
                         reason="R histogram weakens before cross AND prices break opposite",
                         observation=observation)
    if not native_regime and not early_regime and not early_hold:
        return _decision(amount=0, action="REGIME_FLAT",
                         reason="R MACD against side without confirmed pre-cross recovery",
                         observation=observation)

    if current:
        if adverse.severe_adverse_bar and adverse.structure_broken:
            return _decision(amount=0, action="PRICE_SHOCK_FLAT",
                             reason="1m adverse price shock and structure break",
                             observation=observation)
        if side * exit_macd <= 0 and (
                adverse.sustained_adverse or adverse.structure_broken):
            return _decision(amount=0, action="PRICE_CONFIRMED_EXIT_FLAT",
                             reason="E MACD adverse AND recent prices confirm reversal",
                             observation=observation)

    base = macd_stoch_v21_target_v3(
        current_target=TargetInventoryV3(current),
        observation=observation, previous_observation=previous_observation,
        bars=bars, config=config,
    )
    proposed = float(base.target.amount)
    if side * proposed < -1e-9:
        return _decision(amount=current, action="WAIT_ALLOWED_SIDE",
                         reason="V2.1 opposite entry forbidden", observation=observation,
                         base=base)
    if current and proposed == 0:
        return _decision(amount=current, action="HOLD_PRICE_UNCONFIRMED",
                         reason="V2.1 flat ignored until adverse price exit",
                         observation=observation, base=base)
    if side * proposed > side * current + 1e-9:
        if not price.aligned:
            return _decision(amount=current, action="WAIT_PRICE_CONFIRMATION",
                             reason="R/entry MACD lacks favorable 1m price movement",
                             observation=observation, base=base)
        if not native_regime and not early_regime:
            return _decision(amount=current, action="WAIT_REGIME_CONFIRMATION",
                             reason="Early histogram recovery no longer has breakout",
                             observation=observation, base=base)
        if side * exit_macd <= 0:
            if current or not price.strong_breakout:
                return _decision(amount=current, action="WAIT_EXIT_MACD",
                                 reason="E MACD against side, insufficient price override",
                                 observation=observation, base=base)
            return _decision(amount=proposed, action="OPEN_PRICE_OVERRIDE",
                             reason="Strong price breakout overrides E2 for initial OPEN only",
                             observation=observation, base=base)
        if early_regime and not native_regime:
            return _decision(amount=proposed, action="EARLY_HISTOGRAM_PRICE_OPEN",
                             reason="R histogram recovering before cross AND price breakout",
                             observation=observation, base=base)
        return _decision(amount=proposed, action=base.action,
                         reason=base.reason + "; R/E and price confirmed V3",
                         observation=observation, base=base)
    return _decision(amount=current, action="HOLD",
                     reason="R regime valid; price+MACD V3", observation=observation,
                     base=base)


def long_flat_target_v3_price_hist(**kwargs):
    return split_price_hist_regime_v3(side=1, **kwargs)


def short_flat_target_v3_price_hist(**kwargs):
    return split_price_hist_regime_v3(side=-1, **kwargs)
