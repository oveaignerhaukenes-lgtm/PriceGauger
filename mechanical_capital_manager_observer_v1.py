"""Continuous PAPER observer for four V3 strategy decisions on exact canonical 1m.

Pure computational read of supplied fully closed, contiguous bars. All four
research streams update independently of any LIVE account's desired slider,
current V3 execution authority or manager allocation, including weight zero.
Results are 1x research proxies, NEVER broker NAV or accurate leveraged CFD P/L.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_stoch_v2 import macd_stoch_v2_target_v3
from autotrader_v3_macd_stoch_rhythm_build_v1 import macd_stoch_rhythm_build_target_v3
from autotrader_v3_macd_flip_v1 import macd_flip_target_v3
from mechanical_capital_manager_v1 import ObserverPoint, StrategyObserver
from trading_desk import ChartBar

SUPPORTED_SHADOW_KEYS = (
    "macd-stoch-v2-1",
    "macd-stoch-rhythm-build-v1",
    "macd-stoch-v2",
    "macd-flip-v1",
)
DECIDERS = {
    "macd-stoch-v2-1": macd_stoch_v21_target_v3,
    "macd-stoch-rhythm-build-v1": macd_stoch_rhythm_build_target_v3,
    "macd-stoch-v2": macd_stoch_v2_target_v3,
    "macd-flip-v1": macd_flip_target_v3,
}
MAX_1M_BARS = 6000
MIN_WARMUP_MINUTES = 60


def _utc(value) -> datetime:
    stamp = value if isinstance(value,datetime) else datetime.fromisoformat(
        str(value).replace("Z","+00:00")
    )
    if stamp.tzinfo is None:
        raise ValueError("UTC timestamp must have zone")
    return stamp.astimezone(timezone.utc)


def latest_contiguous_completed_1m_v1(
    bars: Sequence, *, asof: datetime,
) -> tuple[ChartBar, ...]:
    if len(bars) > MAX_1M_BARS:
        raise ValueError("1m study exceeds bounded history")
    now = _utc(asof)
    contiguous = []
    previous = None
    for item in bars:
        at = _utc(item.bar_time)
        close = float(item.close)
        high = float(item.high)
        low = float(item.low)
        opening = float(item.open)
        if (not all(isfinite(x) for x in (close,high,low,opening))
                or close <= 0 or low <= 0 or low > high
                or not low <= close <= high or not low <= opening <= high):
            raise ValueError("invalid canonical OHLC bar")
        if previous is not None and at <= previous:
            raise ValueError("canonical 1m bars not strictly ordered")
        previous = at
        if at+timedelta(minutes=1) > now:
            continue
        # Only the most recent contiguous session. No overnight synthetic
        # fills and no forward return across a missing market minute.
        if not contiguous or at - _utc(contiguous[-1].bar_time) != timedelta(minutes=1):
            contiguous = []
        contiguous.append(ChartBar(
            market=str(item.market_name),bar_time=at.isoformat(),
            open=opening,high=high,low=low,close=close,volume=None,
        ))
    return tuple(contiguous)


def shadow_observer_from_completed_bars_v1(
    bars: Sequence[ChartBar], *, instance_id: str, strategy_key: str,
    manual_slider_pct: float, cost_roundtrip_bps: float = 8.,
    max_inventory: float = .03,
) -> StrategyObserver:
    if strategy_key not in SUPPORTED_SHADOW_KEYS:
        raise ValueError("no independent PAPER strategy adapter for this V3 strategy")
    if not 0 <= cost_roundtrip_bps <= 500 or not isfinite(cost_roundtrip_bps):
        raise ValueError("invalid hypothetical roundtrip BBO cost")
    settings = MacdTrailingConfigV3(max_inventory=max_inventory)
    observer = []
    if len(bars) < MIN_WARMUP_MINUTES+15:
        return StrategyObserver(
            instance_id,strategy_key,"PAPER_INDEX_1X",manual_slider_pct,(),
        )
    observations = macd_observations_v2(tuple(bars),timeframe_minutes=1)
    by_time = {x.bar_time:x for x in observations}
    position = 0.
    nav = 1.0
    last_close = None
    decider = DECIDERS[strategy_key]
    for i,bar in enumerate(bars):
        at = _utc(bar.bar_time)
        close = float(bar.close)
        if last_close is not None:
            # Existing virtual inventory from previous closed bar earns
            # subsequent market move; today's decision cannot trade on it.
            signed = position / max_inventory
            nav = max(1.e-8, nav * (1 + signed*(close/last_close-1)))
        last_close = close
        ob = by_time.get(at)
        prev = by_time.get(_utc(bars[i-1].bar_time)) if i else None
        if i >= MIN_WARMUP_MINUTES and ob is not None and prev is not None:
            options = {
                "current_target":TargetInventoryV3(position),
                "observation":ob,"previous_observation":prev,"config":settings,
            }
            if strategy_key != "macd-flip-v1":
                options["bars"]=bars[:i+1]
            decision = decider(**options)
            next_pos = float(decision.target.amount)
            # Close at an *unavailable* next broker fill is not claimed.
            # Idealized closed-bar rebalance + explicit assumed cost, 1x proxy.
            turnover = abs(next_pos-position)/max_inventory
            nav = max(1.e-8, nav *
                      (1 - turnover*cost_roundtrip_bps/20000.))
            position = next_pos
        end = at+timedelta(minutes=1)
        if end.minute % 15 == 0 and i >= MIN_WARMUP_MINUTES:
            observer.append(ObserverPoint(end,nav))
    return StrategyObserver(
        instance_id,strategy_key,"PAPER_INDEX_1X",
        float(manual_slider_pct),tuple(observer),
    )
