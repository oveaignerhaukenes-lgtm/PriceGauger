from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_vwap_regime_histogram_v1 import (
    REGIME_FLAT,
    REGIME_STRONG_BEAR,
    REGIME_WEAK_BEAR,
    classify_vwap_regime_v3,
    vwap_regime_histogram_target_v3,
)


START = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _bars(*, drift: float, volume: float | None = 100.0, count: int = 30):
    rows=[]
    price=25000.0
    for index in range(count):
        price += drift
        rows.append(SimpleNamespace(
            bar_time=START + timedelta(minutes=index),
            open=price-drift,
            high=price+0.5,
            low=price-0.5,
            close=price,
            volume=volume,
        ))
    return tuple(rows)


def _obs(spread: float, minute: int = 30):
    at=START+timedelta(minutes=minute)
    return SimpleNamespace(bar_time=at-timedelta(minutes=2),closed_at=at,spread=spread)


def _decision(*, current: float, previous: float, latest: float, bars):
    return vwap_regime_histogram_target_v3(
        current_target=TargetInventoryV3(current),
        previous_observation=_obs(previous,28),
        observation=_obs(latest,30),
        source_bars=bars,
        config=MacdHistogramConfigV3(tranche=0.01,max_inventory=0.10),
    )


def test_vwap_regime_classifies_strong_and_weak_bear_and_flat():
    strong=classify_vwap_regime_v3(source_bars=_bars(drift=-1.0),closed_at=START+timedelta(minutes=30))
    weak=classify_vwap_regime_v3(source_bars=_bars(drift=-0.05),closed_at=START+timedelta(minutes=30))
    flat=classify_vwap_regime_v3(source_bars=_bars(drift=-0.005),closed_at=START+timedelta(minutes=30))
    assert strong.regime == REGIME_STRONG_BEAR
    assert weak.regime == REGIME_WEAK_BEAR
    assert flat.regime == REGIME_FLAT


def test_strong_bear_never_opens_long_and_reduces_short_on_bullish_pulse():
    bars=_bars(drift=-1.0)
    reduced=_decision(current=-0.03,previous=-1.0,latest=-0.5,bars=bars)
    forbidden=_decision(current=0.01,previous=-1.0,latest=-0.5,bars=bars)
    assert reduced.target.amount == -0.02
    assert reduced.action == "REDUCE"
    assert forbidden.target.amount == 0.0
    assert "forbids LONG" in forbidden.reason


def test_strong_bear_builds_only_when_fast_histogram_aligns():
    decision=_decision(current=-0.03,previous=-1.0,latest=-1.5,bars=_bars(drift=-1.0))
    assert decision.target.amount == -0.04
    assert decision.action == "BUILD"


def test_weak_bear_allows_only_one_long_probe():
    bars=_bars(drift=-0.05)
    first=_decision(current=0.0,previous=-1.0,latest=-0.5,bars=bars)
    second=_decision(current=0.01,previous=-0.5,latest=-0.25,bars=bars)
    assert first.target.amount == 0.01
    assert second.target.amount == 0.01
    assert "one LONG probe" in second.reason


def test_flat_vwap_exits_and_waits():
    decision=_decision(current=0.03,previous=0.2,latest=0.4,bars=_bars(drift=0.005))
    assert decision.target.amount == 0.0
    assert decision.action == "FLAT"
    assert "wait" in decision.reason


def test_missing_volume_holds_instead_of_inventing_vwap():
    decision=_decision(current=-0.03,previous=-1.0,latest=-1.5,bars=_bars(drift=-1.0,volume=None))
    assert decision.target.amount == -0.03
    assert decision.action == "HOLD"
    assert "unavailable" in decision.reason
