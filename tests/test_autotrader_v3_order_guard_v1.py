import pytest
from autotrader_v3_order_guard_v1 import reserve,mark,unresolved,UNRESOLVED

def test_unresolved_states_are_fail_closed():
    assert {'RESERVED','SUBMITTING','SUBMITTED','UNKNOWN'} == set(UNRESOLVED)

def test_pending_intent_persists_and_blocks_second_order(tmp_path):
    db=str(tmp_path/'guard.sqlite')
    scope=dict(account_id='a',uic=4912,asset_type='CfdOnIndex',db_path=db)
    reserve(request_key='first',trader_id='one',**scope)
    assert unresolved(**scope)
    with pytest.raises(Exception):
        reserve(request_key='second',trader_id='two',**scope)
    mark(request_key='first',state='UNKNOWN',db_path=db)
    assert unresolved(**scope)
    mark(request_key='first',state='RECONCILED',db_path=db)
    reserve(request_key='second',trader_id='two',**scope)

def test_independent_accounts_can_reserve(tmp_path):
    db=str(tmp_path/'guard.sqlite')
    reserve(request_key='a',trader_id='one',account_id='a',uic=4912,asset_type='CfdOnIndex',db_path=db)
    reserve(request_key='b',trader_id='two',account_id='b',uic=4912,asset_type='CfdOnIndex',db_path=db)
