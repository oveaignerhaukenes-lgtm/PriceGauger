from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3,set_sim_authority_v3
def test_sim_authority_defaults_off_and_is_explicit(tmp_path):
    db=str(tmp_path/"pg.db")
    assert not sim_authority_armed_v3("t",db_path=db)
    set_sim_authority_v3("t",True,db_path=db); assert sim_authority_armed_v3("t",db_path=db)
    set_sim_authority_v3("t",False,db_path=db); assert not sim_authority_armed_v3("t",db_path=db)
