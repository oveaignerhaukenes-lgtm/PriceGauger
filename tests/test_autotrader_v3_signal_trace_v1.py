"""Signal trace must be bounded, read-only, deduplicated, and not reveal accounts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_v3_signal_trace_v1 import v3_transition_trace, _SEEN, _MAX_KEYS

START=datetime(2026,10,21,10,28,tzinfo=timezone.utc)


def decision(target,action="OPEN",reason="confirmed score",key="2m:2026-10-21T10:28:00Z"):
    return SimpleNamespace(decision_key=key,decision=SimpleNamespace(
        target=SimpleNamespace(amount=target),action=action,reason=reason))


def audit(now=START,actual=-.01,target=.01,approved=None,instance="f3",reason="confirmed score"):
    return v3_transition_trace(
        trader_id=instance,strategy_key="macd-stoch-v2-1",timeframe="2m",
        now=now,actual_amount=actual,decision=decision(target,reason=reason),
        approved_amount=target if approved is None else approved)


def test_one_trace_when_target_opposes_actual():
    _SEEN.clear()
    text=audit()
    assert "actual=-0.01 raw_target=0.01 approved=0.01" in text
    assert "minute=2026-10-21T10:28:00+00:00" in text
    assert audit(now=START+timedelta(seconds=50)) is None
    assert audit(now=START+timedelta(minutes=1)) is not None


def test_zero_delta_does_not_log_and_veto_is_visible():
    _SEEN.clear()
    assert audit(actual=.01,target=.01) is None
    record=audit(actual=-.01,target=.01,approved=0)
    assert "veto=yes" in record
    assert "raw_target=0.01 approved=0" in record
    assert audit(actual=-.01,target=.01,approved=0) is None


def test_bounded_and_sanitize():
    _SEEN.clear()
    out=audit(reason="first line\n second line")
    assert "first line second line" in out
    for i in range(_MAX_KEYS+10):
        audit(instance="f3-"+str(i))
    assert len(_SEEN)==_MAX_KEYS
