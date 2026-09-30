import pytest
from types import SimpleNamespace
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3
from autotrader_v3_live_sizing_v1 import cap_open_add_amount_v3

class Client:
    def _get(self,path,params=None):
        if path.startswith('ref/v1/instruments/details/'):
            return {'AssetType':'CfdOnIndex','IsTradable':True,'NonTradableReason':'None','AmountDecimals':2,
                    'ContractSize':1,'SupportedOrderTypes':['Market'],'CurrencyCode':'USD'}
        if path=='trade/v1/infoprices': return {'Quote':{'Ask':100,'Bid':99}}
        raise AssertionError(path)
class Broker:
    client=Client()
    def precheck(self,order): return {'InstrumentToAccountConversionRate':10}

def test_submission_cap_clamps_open_amount_down_to_step():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    policy=ExecutionPolicyV3('t',budget_nok=2500,exposure_pct=100)
    result=cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='NOK',instrument=instrument,
        side='Buy',requested_amount=3.0,policy=policy)
    assert result.unit_notional_nok==pytest.approx(1000)
    assert result.permitted_amount==pytest.approx(2.5)
    assert result.max_notional_nok==pytest.approx(2500)

def test_non_nok_account_fails_closed():
    with pytest.raises(ValueError,match='NOK Saxo account'):
        cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='USD',
          instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex'),side='Buy',requested_amount=1,
          policy=ExecutionPolicyV3('t',1000,100))


def test_add_cap_counts_existing_same_side_inventory():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    policy=ExecutionPolicyV3('t',budget_nok=2500,exposure_pct=100)
    result=cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='NOK',instrument=instrument,
        side='Buy',requested_amount=1.0,current_same_side_amount=2.0,policy=policy)
    assert result.permitted_amount==pytest.approx(.5)
