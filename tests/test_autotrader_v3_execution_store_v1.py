from autotrader_v3_execution_store_v1 import reserve_intent_v3,intent_status_v3,mark_intent_attempted_v3

def test_intent_reservation_is_durable_and_idempotent(tmp_path):
    db=str(tmp_path/"pg.db")
    assert reserve_intent_v3(intent_id="i1",decision_key="bar1",payload={"x":1},db_path=db)
    assert not reserve_intent_v3(intent_id="i1",decision_key="bar1",payload={"x":1},db_path=db)
    assert intent_status_v3("i1",db_path=db)=="RESERVED"
    mark_intent_attempted_v3("i1",db_path=db)
    assert intent_status_v3("i1",db_path=db)=="ATTEMPTED"
