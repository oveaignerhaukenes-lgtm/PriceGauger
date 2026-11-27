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


def test_archived_fill_requires_exact_account_and_order():
    from autotrader_ic14_live_comparison_v1 import attach_archived_fills
    orders=[dict(account_id="A",broker_order_id="1"),dict(account_id="B",broker_order_id="1")]
    result=attach_archived_fills(orders,{("A","1"):dict(price=100.,filled_at="2026-11-27T09:00:00Z")})
    assert result[0]["fill_evidence"]=="SAXO_FINAL_FILL"
    assert result[0]["fill_price"]==100.
    assert result[1]["fill_price"] is None
    assert result[1]["fill_evidence"]=="NOT_VERIFIED"
    assert attach_archived_fills(orders,None)[0]["fill_evidence"]=="ARCHIVE_UNAVAILABLE"
    assert "account_id" not in result[0]
