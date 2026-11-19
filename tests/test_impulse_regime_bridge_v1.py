"""Impulse-to-regime evidence is causal, same-UIC, research-only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from impulse_regime_bridge_v1 import (
    ImpulsePulse, detect_impulse_pulses_v1, score_impulse_regime_v1,
    summarize_impulse_regime_v1,
)
from tech100_second_impulse_research_v1 import BboSecond


START = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Bar:
    bar_time: datetime
    close: float
    high: float
    low: float


def bars(count=70):
    return tuple(Bar(START+timedelta(minutes=i),
                     1000.0+i, 1001.0+i, 999.0+i)
                 for i in range(count))


def pulse(minute, second, direction="LONG", multiple=1.2):
    at = START + timedelta(minutes=minute, seconds=second)
    return ImpulsePulse(at, at-timedelta(seconds=2), direction,
                        9.0*multiple, multiple, 3, 1000.0)


def test_detects_actual_one_sided_v11_signal_using_receipt_clock():
    session = []
    for i in range(230):
        mid = 27700 + ((i % 8)-4)*0.04
        if 171 <= i <= 176:
            mid += 3*(i-170)
        elif i > 176:
            mid += 18
        at = START + timedelta(seconds=i)
        session.append(BboSecond(at, at+timedelta(seconds=2), mid-0.5, mid+0.5))
    pulses = detect_impulse_pulses_v1((session,))
    assert any(x.direction == "LONG" and x.trigger_points >= 9
               and x.window_seconds in (3,10) for x in pulses)
    assert all(x.observed_at == x.quote_at+timedelta(seconds=2) for x in pulses)
    assert not any(x.direction == "SHORT" for x in pulses)


def test_same_direction_sequence_is_known_at_signal_not_future():
    events = (pulse(2,30), pulse(3,0), pulse(4,1,"SHORT"), pulse(10,0))
    result = score_impulse_regime_v1(events, bars(), as_of=START+timedelta(minutes=70),
                                      horizons=(5,15))
    at_3 = next(o for o in result if o.observed_at == events[1].observed_at
                and o.horizon_minutes == 5)
    assert at_3.prior_same_5m == 2 and at_3.prior_opposite_5m == 0
    assert at_3.sequence == "2"
    at_4 = next(o for o in result if o.observed_at == events[2].observed_at
                and o.horizon_minutes == 5)
    assert at_4.prior_same_5m == 1 and at_4.prior_opposite_5m == 2
    assert at_4.sequence == "MOTSTRIDENDE"
    at_10 = next(o for o in result if o.observed_at == events[3].observed_at
                 and o.horizon_minutes == 5)
    assert at_10.prior_same_5m == 1 and at_10.prior_opposite_5m == 0
    assert at_10.sequence == "1"


def test_future_1m_prices_are_after_first_available_completed_bar():
    p = pulse(2,30)
    result = score_impulse_regime_v1((p,), bars(),
                                     as_of=START+timedelta(minutes=8),
                                     horizons=(5,15,30))
    assert len(result) == 1
    assert result[0].horizon_minutes == 5
    assert result[0].signed_forward_points == 5.0
    assert result[0].signed_forward_pct == pytest.approx(100*5/1002)
    assert result[0].max_favorable_points == 6.0
    assert result[0].max_adverse_points == 0.0
    # At 07:59, the target 07:00-08:00 bar is not completed yet.
    assert not score_impulse_regime_v1((p,), bars(),
        as_of=START+timedelta(minutes=7,seconds=59), horizons=(5,))


def test_gaps_and_missing_anchor_refuse_outcomes_not_interpolated():
    p = pulse(2,30)
    assert not score_impulse_regime_v1((p,), bars()[3:],
        as_of=START+timedelta(minutes=50), horizons=(5,))
    gapped = tuple(b for b in bars() if b.bar_time != START+timedelta(minutes=5))
    assert not score_impulse_regime_v1((p,), gapped,
        as_of=START+timedelta(minutes=50), horizons=(5,))


def test_training_outcome_must_mature_before_holdout_cutoff():
    p1,p2,p3 = pulse(2,30),pulse(10,0),pulse(40,0)
    results = score_impulse_regime_v1((p1,p2,p3),bars(),
        as_of=START+timedelta(minutes=70),horizons=(5,15,30))
    summary = summarize_impulse_regime_v1(results,
        cutoff=START+timedelta(minutes=20),min_samples=1)
    at_15 = [g for g in summary if g["Minutter"]==15 and g["Måling"]=="REKKE"]
    # 2:30+15m price label is available before the split; 10:00+15m is NOT.
    assert sum(g["Hendelser"] for g in at_15 if g["Del"]=="KALIBRERING") == 1
    assert sum(g["Hendelser"] for g in at_15 if g["Del"]=="HOLDOUT") == 1
    assert {g["Kategori"] for g in at_15} == {"1"}


def test_research_cannot_modify_live_filter_or_place_order():
    source = Path("impulse_regime_bridge_v1.py").read_text(encoding="utf8")
    assert "set_trade_filter_v1" not in source
    assert "place_order(" not in source
    assert "SaxoClient" not in source
    assert "pg_v3_impulse_signal_events" not in source
