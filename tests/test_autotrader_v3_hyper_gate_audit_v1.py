"""HyperChase gated decision counter remains observational and bounded."""
from datetime import datetime, timedelta, timezone

from autotrader_v3_hyper_gate_audit_v1 import (
    _RECORDS, _MAX_INSTANCES, count_hyper_decision,
)

BASE=datetime(2026,10,21,14,52,tzinfo=timezone.utc)


def log(trader="a", now=BASE, action="NEED_QUOTES", raw=0, approved=0):
    return count_hyper_decision(
        trader_id=trader,strategy_key="hyper-chase-10s-fast-v1",
        now=now,action=action,actual_amount=0,
        raw_target=raw,approved_target=approved,
    )


def test_minute_rollover_summarizes_rejections_and_veto():
    _RECORDS.clear()
    assert log() is None
    assert log(now=BASE+timedelta(seconds=10), action="STALE_QUOTES") is None
    assert log(now=BASE+timedelta(seconds=12),action="CHASE_LONG",
               raw=.01,approved=0) is None
    old=log(now=BASE+timedelta(minutes=1),action="WAIT_BELOW_THRESHOLD")
    assert "minute=2026-10-21T14:52:00+00:00" in old
    assert "NEED_QUOTES:1" in old
    assert "STALE_QUOTES:1" in old
    assert "CHASE_LONG:1" in old
    assert "RISK_VETO:1" in old
    assert "evaluations=3" in old  # Exactly three strategy evaluations, not trades.


def test_flat_sustained_counts_do_not_spam():
    _RECORDS.clear()
    for second in range(35):
        assert log(now=BASE+timedelta(seconds=second)) is None
    summary=log(now=BASE+timedelta(minutes=1))
    assert "NEED_QUOTES:35" in summary


def test_memory_bound_and_bad_input():
    _RECORDS.clear()
    for n in range(_MAX_INSTANCES+7):
        log(trader="bot-"+str(n))
    assert len(_RECORDS)==_MAX_INSTANCES
    assert log(trader="bad",raw=float("nan")) is None
