import pytest
from autotrader_v3_order_audit_v1 import verified_final_fill_v3,fetch_exact_order_audit_v3

BASE=dict(OrderId='order-1',AccountId='a',Uic=4912,AssetType='CfdOnIndex',Status='FinalFill',SubStatus='Confirmed',FilledAmount=0.1)
SCOPE=dict(order_id='order-1',account_id='a',uic=4912,asset_type='CfdOnIndex')

def test_audit_requires_exact_confirmed_single_fill():
    assert verified_final_fill_v3([BASE],**SCOPE)==BASE
    for field,value in [('OrderId','other'),('AccountId','other'),('Uic',123),('AssetType','Stock'),('Status','Pending'),('SubStatus','Unconfirmed'),('FilledAmount',0)]:
        assert verified_final_fill_v3([{**BASE,field:value}],**SCOPE) is None
    assert verified_final_fill_v3([BASE,BASE],**SCOPE) is None
    assert verified_final_fill_v3([BASE],**{**SCOPE,'order_id':''}) is None

def test_incomplete_audit_cannot_clear_order():
    class Client:
        def _get(self,path,params):
            return {'Data':[BASE]*500}
    class Broker:
        client=Client()
    with pytest.raises(RuntimeError,match='incomplete'):
        fetch_exact_order_audit_v3(Broker(),account_key='key',client_key='client')
