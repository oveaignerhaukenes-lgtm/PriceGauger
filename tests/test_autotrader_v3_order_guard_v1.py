import pytest
from autotrader_v3_order_guard_v1 import reserve,mark,unresolved,pending_order,order_state,UNRESOLVED

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


def test_expected_post_order_inventory_is_durable(tmp_path):
    db=str(tmp_path/'guard.sqlite')
    scope=dict(account_id='a',uic=4912,asset_type='CfdOnIndex',db_path=db)
    reserve(request_key='buy-1',trader_id='pilot',expected_inventory=0.3,
            submitted_amount=0.1,submitted_side='Buy',**scope)
    mark(request_key='buy-1',state='SUBMITTING',db_path=db)
    mark(request_key='buy-1',state='SUBMITTED',broker_order_id='saxo-123',db_path=db)
    stored=pending_order(**scope)
    assert stored['broker_order_id']=='saxo-123'
    assert stored['expected_inventory']==0.3
    assert stored['submitted_amount']==0.1
    assert stored['submitted_side']=='Buy'
    assert stored['state']=='SUBMITTED'


def test_concurrent_workers_cannot_reserve_same_boundary(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from autotrader_v3_order_guard_v1 import ensure_schema
    db=str(tmp_path/'concurrent.sqlite')
    ensure_schema(db)
    def reserve_worker(index):
        try:
            reserve(request_key=f'order-{index}',trader_id=f'worker-{index}',
                account_id='shared',uic=4912,asset_type='CfdOnIndex',db_path=db)
            return True
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(reserve_worker,(1,2)))
    assert results.count(True)==1
    assert results.count(False)==1

def test_existing_guard_table_is_migrated_in_place(tmp_path):
    import sqlite3
    from autotrader_v3_order_guard_v1 import pending_order
    db=str(tmp_path/'legacy.sqlite')
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE autotrader_v3_order_guard (
            request_key TEXT PRIMARY KEY,trader_id TEXT NOT NULL,
            account_id TEXT NOT NULL,uic INTEGER NOT NULL,asset_type TEXT NOT NULL,
            state TEXT NOT NULL,broker_order_id TEXT,detail TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("""INSERT INTO autotrader_v3_order_guard
            (request_key,trader_id,account_id,uic,asset_type,state)
            VALUES('legacy','trader','a',4912,'CfdOnIndex','UNKNOWN')""")
    pending=pending_order(account_id='a',uic=4912,asset_type='CfdOnIndex',db_path=db)
    assert pending['request_key']=='legacy'
    assert pending['expected_inventory'] is None
    with pytest.raises(Exception):
        reserve(request_key='new',trader_id='new',account_id='a',uic=4912,
                asset_type='CfdOnIndex',db_path=db)


def test_rejected_request_is_terminal_and_queryable(tmp_path):
    db=str(tmp_path/'guard.sqlite')
    scope=dict(account_id='a',uic=4912,asset_type='CfdOnIndex',db_path=db)
    reserve(request_key='reject-1',trader_id='pilot',expected_inventory=-0.08,
            submitted_amount=0.01,submitted_side='Sell',**scope)
    mark(request_key='reject-1',state='UNKNOWN',
         detail='SaxoError: REQUEST_FAILED · HTTP 400: WouldExceedMargin',db_path=db)
    pending=pending_order(**scope)
    assert pending['detail'].endswith('WouldExceedMargin')
    mark(request_key='reject-1',state='REJECTED',detail=pending['detail'],db_path=db)
    assert order_state(request_key='reject-1',db_path=db)=='REJECTED'
    assert pending_order(**scope) is None
