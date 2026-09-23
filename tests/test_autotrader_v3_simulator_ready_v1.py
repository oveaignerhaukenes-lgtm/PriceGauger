from autotrader_strategy_catalog_v2 import strategy_spec_v2
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3
from autotrader_v3_sim_authority_v1 import any_sim_authority_armed_v3,set_sim_authority_v3

def test_macd_trailing_is_available_to_simulator_catalog():
    spec=strategy_spec_v2(STRATEGY_KEY_V3)
    assert spec.can_long and spec.can_short
    assert "Trailing" in spec.label

def test_any_sim_authority_defaults_off(tmp_path):
    db=str(tmp_path/"pg.db")
    assert not any_sim_authority_armed_v3(db_path=db)
    set_sim_authority_v3("t",True,db_path=db)
    assert any_sim_authority_armed_v3(db_path=db)
