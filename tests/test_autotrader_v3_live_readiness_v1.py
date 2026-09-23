import pytest
from types import SimpleNamespace
from autotrader_v3_live_authority_v1 import live_authority_armed_v3,set_live_authority_v3
from autotrader_v3_live_readiness_v1 import live_readiness_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_sim_authority_v1 import set_sim_authority_v3

def enrollment():
    return SimpleNamespace(strategy_key=STRATEGY_KEY_V3,execution_mode="LIVE_MANAGE",enabled=True,pilot_key="t")
def test_live_authority_defaults_off(tmp_path):
    db=str(tmp_path/"pg.db"); assert not live_authority_armed_v3("t",db_path=db)
def test_live_readiness_requires_explicit_arm_live_endpoint_and_flat(tmp_path):
    db=str(tmp_path/"pg.db"); e=enrollment()
    assert not live_readiness_v3(e,broker_is_live=True,exact_inventory=0,db_path=db).ready
    set_live_authority_v3("t",True,db_path=db)
    assert live_readiness_v3(e,broker_is_live=True,exact_inventory=0,db_path=db).ready
    assert not live_readiness_v3(e,broker_is_live=True,exact_inventory=.01,db_path=db).ready
    set_sim_authority_v3("t",True,db_path=db)
    assert not live_readiness_v3(e,broker_is_live=True,exact_inventory=0,db_path=db).ready
