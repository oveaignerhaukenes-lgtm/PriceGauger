from types import SimpleNamespace
from autotrader_v3_order_reconciliation_v1 import (
    verified_reconciled_inventory_v3,reconcile_pending_v3)

SCOPE=dict(account_id='a',uic=4912,asset_type='CfdOnIndex')
PENDING=dict(request_key='r1',broker_order_id='o1',expected_inventory=0.2,
             submitted_amount=0.1,submitted_side='Buy')
FILL=dict(OrderId='o1',AccountId='a',Uic=4912,AssetType='CfdOnIndex',
          Status='FinalFill',SubStatus='Confirmed',FilledAmount=0.1,BuySell='Buy',LogId='log1')
POSITION=SimpleNamespace(account_id='a',uic=4912,asset_type='CfdOnIndex',
                         direction='LONG',amount=0.2)

def verify(pending=PENDING,rows=None,observations=None,**scope):
    return verified_reconciled_inventory_v3(pending=pending,
        rows=[FILL] if rows is None else rows,
        observations=[POSITION] if observations is None else observations,
        **(scope or SCOPE))

def test_exact_fill_and_independent_position_required():
    assert verify()
    assert not verify(pending={**PENDING,'broker_order_id':''})
    assert not verify(pending={**PENDING,'expected_inventory':None})
    assert not verify(rows=[{**FILL,'FilledAmount':0.05}])
    assert not verify(rows=[{**FILL,'BuySell':'Sell'}])
    assert not verify(rows=[{**FILL,'AccountId':'b'}])
    assert not verify(rows=[FILL,FILL])
    assert not verify(observations=[])
    assert not verify(observations=[POSITION,POSITION])
    assert not verify(observations=[SimpleNamespace(**{**vars(POSITION),'amount':0.1})])

def test_reconciliation_never_releases_without_both_evidences(monkeypatch):
    import autotrader_v3_order_reconciliation_v1 as module
    monkeypatch.setattr(module,'fetch_exact_order_audit_v3',lambda *a,**kw:[FILL])
    marked=[]
    class Broker:
        client=object()
    kwargs=dict(broker=Broker(),pending=PENDING,**SCOPE,
        account_key='account-key',client_key='client-key',
        mark_reconciled=lambda **kw:marked.append(kw),db_path='unused')
    assert not reconcile_pending_v3(read_positions=lambda client:[],**kwargs)
    assert not marked
    assert reconcile_pending_v3(read_positions=lambda client:[POSITION],**kwargs)
    assert marked[0]['request_key']=='r1'
    assert marked[0]['state']=='RECONCILED'

def test_distinct_partial_fills_require_complete_amount_and_exact_position():
    first={**FILL,'Status':'PartialFill','FilledAmount':0.04,'LogId':'log-a'}
    second={**FILL,'Status':'FinalFill','FilledAmount':0.06,'LogId':'log-b'}
    assert verify(rows=[first,second])
    assert not verify(rows=[first])
    assert not verify(rows=[first,{**second,'LogId':'log-a'}])
    assert not verify(rows=[first,{**second,'AccountId':'other'}])
    assert not verify(rows=[first,{**second,'FilledAmount':0.07}])
