"""Read-only HyperChase quote-density probe does not manufacture 1 Hz samples."""
from datetime import datetime,timedelta,timezone

from hyper_chase_quote_quality_probe_v1 import summarize_hyper_quote_window

BASE=datetime(2026,10,21,8,0,tzinfo=timezone.utc)


def quote(n, uic=4912, bid=30000., ask=30001., received_lag=0):
    at=BASE+timedelta(seconds=n)
    return {
        "provider_uic":uic,"quote_at":at.isoformat(),
        "received_at":(at+timedelta(seconds=received_lag)).isoformat(),
        "bid":bid,"ask":ask,
    }


def test_continuous_1hz_is_eligible_even_when_momentum_is_small():
    rows=[quote(n) for n in range(60)]
    result=summarize_hyper_quote_window(rows,now=BASE+timedelta(seconds=59))
    assert len(result)==1
    assert result[0]["quotes_60s"]==60
    assert result[0]["valid_10s_windows"]>=49
    assert result[0]["max_gap_s"]==1


def test_gapped_quotes_never_count_as_valid_ten_second_windows():
    rows=[quote(n) for n in range(0,60,5)]
    result=summarize_hyper_quote_window(rows,now=BASE+timedelta(seconds=59))
    assert result[0]["valid_10s_windows"]==0
    assert result[0]["max_gap_s"]==5


def test_wide_spread_delayed_quotes_and_independent_uics():
    rows=[quote(n) for n in range(12)]
    rows += [quote(n,uic=9912,bid=30000,ask=30030) for n in range(12)]
    rows += [quote(12,received_lag=10)]
    result=summarize_hyper_quote_window(rows,now=BASE+timedelta(seconds=13))
    assert len(result)==2
    assert result[0]["uic"]==4912
    assert result[0]["quotes_60s"]==12
    assert result[0]["valid_10s_windows"]>0
    assert result[1]["uic"]==9912
    assert result[1]["wide_spread_quotes"]==12
    assert result[1]["valid_10s_windows"]==0


def test_no_quotes_no_activity():
    assert summarize_hyper_quote_window([],now=BASE)==[]
