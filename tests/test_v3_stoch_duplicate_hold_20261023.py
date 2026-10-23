"""Regression: live 1m/2m duplicate bars cannot crash MACD+Stoch V1."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest

from database import connect
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_macd_histogram_v1 import MacdHistogramDecisionV3
from autotrader_v3_macd_stoch_v1 import STRATEGY_KEY_V3 as STOCH_V1
from autotrader_v3_macd_stoch_v2 import STRATEGY_KEY_V3 as STOCH_V2
from autotrader_v3_macd_flip_v1 import STRATEGY_KEY_V3 as FLIP
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING

START=datetime(2026,10,23,7,0,tzinfo=timezone.utc)


def observation(n):
    return MacdObservationV2(
        bar_time=START+timedelta(minutes=2*n),macd=1.0,
        signal=0.0,
    )


def bars():
    return tuple(SimpleNamespace(
        high=101.,low=99.,close=100.
    )for _ in range(50))


@pytest.mark.parametrize("strategy",(STOCH_V1,STOCH_V2,FLIP,TRAILING))
def test_duplicate_hold_does_not_reopen_or_raise(tmp_path,strategy):
    path=str(tmp_path/"pg.db")
    trader="trader-"+strategy
    first=evaluate_closed_bar_once_v3(
        trader_id=trader,strategy_key=strategy,observation=observation(0),
        bars=bars(),db_path=path,
    )
    assert first.is_new
    with connect(path,force_sqlite=True) as db:
        before=dict(db.execute(
            "SELECT last_bar_time,target_amount,previous_spread,updated_at "
            "FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            (trader,)).fetchone())
    for n in range(3):
        duplicate=evaluate_closed_bar_once_v3(
            trader_id=trader,strategy_key=strategy,observation=observation(0),
            bars=bars(),db_path=path,
        )
        assert duplicate.is_new is False
        assert duplicate.decision.action=="HOLD_DUPLICATE"
        assert isinstance(duplicate.decision,MacdHistogramDecisionV3)
        assert duplicate.decision.target==first.decision.target
        assert duplicate.decision_key==first.decision_key
    with connect(path,force_sqlite=True) as db:
        after=dict(db.execute(
            "SELECT last_bar_time,target_amount,previous_spread,updated_at "
            "FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            (trader,)).fetchone())
    assert after==before


def test_replayed_stoch_v1_does_not_suppress_next_genuine_bar(tmp_path):
    path=str(tmp_path/"pg.db")
    kwargs={"trader_id":"stoch-v1-live","strategy_key":STOCH_V1,
            "bars":bars(),"db_path":path}
    first=evaluate_closed_bar_once_v3(observation=observation(0),**kwargs)
    duplicate=evaluate_closed_bar_once_v3(observation=observation(0),**kwargs)
    next_real=evaluate_closed_bar_once_v3(observation=observation(1),**kwargs)
    assert first.is_new
    assert duplicate.is_new is False
    assert next_real.is_new
    assert next_real.decision_key!=duplicate.decision_key
