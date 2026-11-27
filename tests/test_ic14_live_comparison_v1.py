from datetime import datetime,timedelta,timezone
from autotrader_ic14_live_comparison_v1 import compare_signals

def test_same_timestamp_and_reason_required_for_exact_match():
    t=datetime(2026,11,27,9,tzinfo=timezone.utc)
    trace=[dict(at=t,decision="QUALIFIED_IMPULSE_V14",mid=100),
           dict(at=t+timedelta(seconds=30),decision="CONFIRMED_EXIT",mid=110),
           dict(at=t+timedelta(seconds=31),decision=None,mid=111)]
    observed=[dict(quote_at=t.isoformat(),action="QUALIFIED_IMPULSE_V14",source_mid=100),
              dict(quote_at=(t+timedelta(seconds=30)).isoformat(),action="URGENT_REVERSAL",source_mid=110)]
    counts,events=compare_signals(trace,observed)
    by={r["signal"]:r for r in counts}
    assert by["QUALIFIED_IMPULSE_V14"]["exact_matches"]==1
    assert by["CONFIRMED_EXIT"]["worker"]==0
    assert by["URGENT_REVERSAL"]["preview"]==0
    assert len(events)==3
    assert compare_signals([],[])==([],[])
