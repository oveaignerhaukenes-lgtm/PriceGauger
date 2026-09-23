from autotrader_v3_modifier_selection_v1 import *

def test_v3_modifier_selection_persists(tmp_path):
    db=str(tmp_path/"pg.db"); key="t"
    assert load_modifier_selection_v3(key,db)==ModifierSelectionV3()
    save_modifier_selection_v3(key,ModifierSelectionV3(True,True,False),db)
    assert load_modifier_selection_v3(key,db)==ModifierSelectionV3(True,True,False)
