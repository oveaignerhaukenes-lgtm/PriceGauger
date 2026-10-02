from autotrader_v3_control_plane_v1 import authority_state_v3, set_live_enabled_v3, set_sim_enabled_v3

def test_v3_control_plane_keeps_live_and_sim_mutually_exclusive(tmp_path):
    db = str(tmp_path / "pg.db")
    state = set_live_enabled_v3("pilot", True, db_path=db)
    assert state.live_armed is True
    assert state.sim_armed is False

    state = set_sim_enabled_v3("pilot", True, db_path=db)
    assert state.live_armed is False
    assert state.sim_armed is True

    state = set_sim_enabled_v3("pilot", False, db_path=db)
    assert state.live_armed is False
    assert state.sim_armed is False
    assert authority_state_v3("pilot", db_path=db) == state
