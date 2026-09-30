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

def test_cash_budget_does_not_cap_leveraged_gross_notional():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    policy=ExecutionPolicyV3('t',budget_nok=2500,exposure_pct=100)
    result=cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='NOK',instrument=instrument,
        side='Buy',requested_amount=3.0,policy=policy)
    assert result.unit_notional_nok==pytest.approx(1000)
    assert result.permitted_amount==pytest.approx(3.0)
    assert result.max_notional_nok==pytest.approx(2500)

def test_non_nok_account_fails_closed():
    with pytest.raises(ValueError,match='NOK Saxo account'):
        cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='USD',
          instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex'),side='Buy',requested_amount=1,
          policy=ExecutionPolicyV3('t',1000,100))


def test_existing_same_side_inventory_does_not_create_false_cash_spend():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    policy=ExecutionPolicyV3('t',budget_nok=2500,exposure_pct=100)
    result=cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='NOK',instrument=instrument,
        side='Buy',requested_amount=1.0,current_same_side_amount=2.0,policy=policy)
    assert result.permitted_amount==pytest.approx(1.0)


def test_missing_account_currency_has_specific_fail_closed_reason():
    with pytest.raises(ValueError,match='account currency unavailable'):
        cap_open_add_amount_v3(broker=Broker(),account_key='k',account_currency='',
          instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex'),side='Buy',requested_amount=1,
          policy=ExecutionPolicyV3('t',1000,100))


class LargeContractClient(Client):
    def _get(self,path,params=None):
        if path.startswith('ref/v1/instruments/details/'):
            return {'AssetType':'CfdOnIndex','IsTradable':True,'NonTradableReason':'None','AmountDecimals':2,
                    'ContractSize':100,'SupportedOrderTypes':['Market'],'CurrencyCode':'USD'}
        return super()._get(path,params=params)

class LargeContractBroker(Broker):
    client=LargeContractClient()

def test_index_cfd_contract_size_is_not_double_applied_to_exposure_unit():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    result=cap_open_add_amount_v3(broker=LargeContractBroker(),account_key='k',account_currency='NOK',
        instrument=instrument,side='Buy',requested_amount=.01,policy=ExecutionPolicyV3('t',2000,100))
    assert result.unit_notional_nok==pytest.approx(1000)
    assert result.permitted_amount==pytest.approx(.01)

class Tech100LikeClient(Client):
    def _get(self,path,params=None):
        if path.startswith('ref/v1/instruments/details/'):
            return {'AssetType':'CfdOnIndex','IsTradable':True,'NonTradableReason':'None','AmountDecimals':2,
                    'ContractSize':1,'SupportedOrderTypes':['Market'],'CurrencyCode':'USD'}
        if path=='trade/v1/infoprices': return {'Quote':{'Ask':25000,'Bid':24999}}
        raise AssertionError(path)

class Tech100LikeBroker(Broker):
    client=Tech100LikeClient()

def test_tech100_minimum_lot_is_not_blocked_by_gross_notional():
    instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex')
    result=cap_open_add_amount_v3(broker=Tech100LikeBroker(),account_key='k',account_currency='NOK',
        instrument=instrument,side='Buy',requested_amount=.01,policy=ExecutionPolicyV3('t',2000,100))
    assert result.unit_notional_nok==pytest.approx(250000)
    assert result.permitted_amount==pytest.approx(.01)
