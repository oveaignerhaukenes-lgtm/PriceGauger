from datetime import datetime,timezone
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3

def obs(minute,spread):
    return MacdObservationV2(bar_time=datetime(2026,9,23,0,minute,tzinfo=timezone.utc),macd=spread,signal=0.0)

def test_closed_bar_driver_applies_each_bar_once_across_calls(tmp_path):
    db=str(tmp_path/"pg.db")
    a=evaluate_closed_bar_once_v3(trader_id="t",observation=obs(5,1),db_path=db)
    b=evaluate_closed_bar_once_v3(trader_id="t",observation=obs(5,1),db_path=db)
    c=evaluate_closed_bar_once_v3(trader_id="t",observation=obs(10,1),db_path=db)
    assert a.is_new and a.decision.target.amount==0.01
    assert not b.is_new and b.decision.target.amount==0.01
    assert c.is_new and c.decision.target.amount==0.01
    assert c.decision.action=="HOLD"

def test_closed_bar_driver_rejects_older_bar_as_duplicate(tmp_path):
    db=str(tmp_path/"pg.db")
    evaluate_closed_bar_once_v3(trader_id="t",observation=obs(10,1),db_path=db)
    old=evaluate_closed_bar_once_v3(trader_id="t",observation=obs(5,-1),db_path=db)
    assert not old.is_new
    assert old.decision.target.amount==0.01
