from datetime import datetime,timedelta,timezone
from math import sin
import pytest
from autotrader_ic14_auto_v1 import propose_ic14
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_impulse_catcher_v14 import config_v14,normalize_settings

NOW=datetime(2026,11,25,12,tzinfo=timezone.utc)

def series(sign=1,scale=1):
    return [ImpulseQuote(NOW-timedelta(seconds=3600-i),p-.5,p+.5)
        for i in range(3601)
        for p in [26000+sign*scale*(8*sin(i/15)+2*sin(i/2.7)+i*.002)]]

@pytest.mark.parametrize("side,sign",[("LONG",1),("SHORT",-1)])
def test_auto_proposes_only_main_controls_and_keeps_existing_safety(side,sign):
    current=normalize_settings({"urgent_retrace_points":20.,"maximum_spread_points":4.,
                                "entry_indicators":["rsi"],"atr_entry_multiple":1.})
    quotes=series(sign)
    proposal=propose_ic14(quotes,now=NOW,side=side,current=current)
    main={"min_impulse_points","entry_confirmation_seconds","minimum_hold_seconds",
          "retrace_fraction","exit_confirmation_seconds"}
    assert all(proposal.settings[k]==v for k,v in current.items() if k not in main)
    assert proposal.evidence["quotes"]==3601
    assert proposal.evidence["spread"]==1.
    assert proposal.evidence["directional_p85"]>0
    assert proposal.evidence["runs"]>15
    assert proposal.evidence["gap_seconds"]==0
    assert config_v14(side,proposal.settings).urgent_retrace_points==20.
    assert current["min_impulse_points"]==9.
    # Future quotes must not affect a fixed as-of proposal.
    extra=ImpulseQuote(NOW+timedelta(seconds=1),30000.,30001.)
    assert propose_ic14(quotes+[extra],now=NOW,side=side,current=current)==proposal

def test_auto_refuses_stale_sparse_and_gapped_data():
    quotes=series()
    for q in (quotes[:-20],quotes[::4],quotes[:1000]+quotes[1500:]):
        with pytest.raises(ValueError):
            propose_ic14(q,now=NOW,side="LONG",current={})

def test_auto_directional_scale_responds_to_signal_amplitude():
    a=propose_ic14(series(scale=1),now=NOW,side="LONG",current={})
    b=propose_ic14(series(scale=4),now=NOW,side="LONG",current={})
    assert b.evidence["directional_p85"]>a.evidence["directional_p85"]
    assert b.settings["min_impulse_points"]>a.settings["min_impulse_points"]
