import pytest
from types import SimpleNamespace
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3
from autotrader_v3_live_sizing_v1 import (
    cap_open_add_amount_v3,
    capital_requirement_nok_v3,
    enforce_execution_policy_precheck_v3,
)

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
    assert result.unit_notional_nok==pytest.approx(100)
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
    assert result.unit_notional_nok==pytest.approx(100)
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
    assert result.unit_notional_nok==pytest.approx(25000)
    assert result.permitted_amount==pytest.approx(.01)


class NoPrecheckBroker(Broker):
    def precheck(self,order):
        raise AssertionError("sizing must not consume Saxo order precheck")

def test_sizing_does_not_consume_order_precheck_rate_limit():
    result=cap_open_add_amount_v3(broker=NoPrecheckBroker(),account_key='k',account_currency='NOK',
        instrument=SimpleNamespace(uic=1,asset_type='CfdOnIndex'),side='Buy',requested_amount=.01,
        policy=ExecutionPolicyV3('t',2000,100))
    assert result.permitted_amount==pytest.approx(.01)


def test_v3_capital_requirement_prefers_broker_initial_margin_for_leveraged_order():
    precheck={
        'PreCheckResult':'Ok',
        'EstimatedCashRequired':5000,
        'EstimatedCashRequiredCurrency':'NOK',
        'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':250},
    }
    assert capital_requirement_nok_v3(
        precheck=precheck,side='Buy',account_currency='NOK') == pytest.approx(250)


def test_v3_capital_requirement_uses_cash_when_margin_is_zero():
    precheck={
        'PreCheckResult':'Ok',
        'EstimatedCashRequired':750,
        'EstimatedCashRequiredCurrency':'NOK',
        'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':0},
    }
    assert capital_requirement_nok_v3(
        precheck=precheck,side='Buy',account_currency='NOK') == pytest.approx(750)


def test_budget_times_exposure_is_an_enforced_broker_cap():
    policy=ExecutionPolicyV3('t',budget_nok=2000,exposure_pct=50)
    ok={
        'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':999},
    }
    assert enforce_execution_policy_precheck_v3(
        precheck=ok,side='Buy',account_currency='NOK',policy=policy) == pytest.approx(999)
    too_large={
        'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':1001},
    }
    with pytest.raises(ValueError,match='exceeds configured cap 1000.00 NOK'):
        enforce_execution_policy_precheck_v3(
            precheck=too_large,side='Buy',account_currency='NOK',policy=policy)


def test_capital_requirement_fails_closed_on_unproven_currency_or_missing_evidence():
    with pytest.raises(ValueError,match='expected NOK'):
        capital_requirement_nok_v3(
            precheck={'MarginImpactBuySell':{'Currency':'USD','InitialMarginBuy':10}},
            side='Buy',account_currency='NOK')
    with pytest.raises(ValueError,match='did not expose broker capital requirement'):
        capital_requirement_nok_v3(
            precheck={'MarginImpactBuySell':{}},side='Buy',account_currency='NOK')


def test_incremental_build_cannot_bypass_cumulative_cap():
    policy=ExecutionPolicyV3('t',budget_nok=300,exposure_pct=100)
    step={
        'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':147},
    }
    # First 0.01 uses 147 NOK; second projects 294 NOK and is still inside cap.
    assert enforce_execution_policy_precheck_v3(
        precheck=step,side='Buy',account_currency='NOK',policy=policy,
        current_same_side_amount=0.01,order_amount=0.01,
    ) == pytest.approx(294)
    # Third 0.01 would project 441 NOK total and must be stopped.
    with pytest.raises(ValueError,match='cumulative capital requirement 441.00 NOK exceeds configured cap 300.00 NOK'):
        enforce_execution_policy_precheck_v3(
            precheck=step,side='Buy',account_currency='NOK',policy=policy,
            current_same_side_amount=0.02,order_amount=0.01,
        )


def test_open_cap_semantics_remain_order_margin_when_flat():
    policy=ExecutionPolicyV3('t',budget_nok=300,exposure_pct=100)
    precheck={'MarginImpactBuySell':{'Currency':'NOK','InitialMarginBuy':250}}
    assert enforce_execution_policy_precheck_v3(
        precheck=precheck,side='Buy',account_currency='NOK',policy=policy,
        current_same_side_amount=0.0,order_amount=0.01,
    ) == pytest.approx(250)
