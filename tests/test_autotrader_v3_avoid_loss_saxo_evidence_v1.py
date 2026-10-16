"""Saxo source parity and currency/cost validation; no network or broker mutation."""
from datetime import datetime,timezone,timedelta
from copy import deepcopy

import pytest

from autotrader_v3_avoid_loss_v1 import (
    ConfirmedPositionV1, inspect_open_position_v1, AvoidLossStateV1,
)
from autotrader_v3_avoid_loss_saxo_evidence_v1 import (
    precheck_margin_nok_v1, validated_saxo_pnl_v1,
)

NOW=datetime(2026,10,16,12,0,tzinfo=timezone.utc)
POSITION=ConfirmedPositionV1("autotrader",12345,"CfdOnIndex","NP-1",.01,1000.0)


def precheck():
    return {"PreCheckResult":"Ok","MarginImpactBuySell":{
        "Currency":"NOK","InitialMarginBuy":1000,"InitialMarginSell":1100,
    }}


def netposition():
    return {
        "NetPositionId":"NP-1",
        "NetPositionBase":{
            "PositionsAccount":"autotrader","Uic":12345,
            "AssetType":"CfdOnIndex","AmountLong":.01,"AmountShort":0.0,
        },
        "NetPositionView":{
            "Status":"Open",
            "CalculationReliability":"Ok",
            "CurrentPriceDelayMinutes":0,
            "CurrentPriceLastTraded":NOW.isoformat(),
            "ProfitLossOnTrade":70.0,  # DO NOT use: instrument USD
            "ProfitLossOnTradeInBaseCurrency":30.0,
            "TradeCostsTotalInBaseCurrency":7.0,
        },
    }


def sample(row=None,extra=3.0):
    return validated_saxo_pnl_v1(
        row=row or netposition(),position=POSITION,
        account_currency="NOK",verified_base_currency="NOK",
        estimated_exit_cost_nok=extra,received_at=NOW)


def test_entry_precheck_must_be_ok_and_explicit_nok():
    assert precheck_margin_nok_v1(precheck(),side="Buy")==1000
    assert precheck_margin_nok_v1(precheck(),side="Sell")==1100
    for bad in (
        {"PreCheckResult":"Rejected","MarginImpactBuySell":precheck()["MarginImpactBuySell"]},
        {"PreCheckResult":"Ok","MarginImpactBuySell":{"InitialMarginBuy":1000}},
        {"PreCheckResult":"Ok","MarginImpactBuySell":{"Currency":"USD","InitialMarginBuy":1000}},
        {"PreCheckResult":"Ok","MarginImpactBuySell":{"Currency":"NOK","InitialMarginBuy":0}},
    ):
        with pytest.raises(ValueError):
            precheck_margin_nok_v1(bad,side="Buy")
    with pytest.raises(ValueError):
        precheck_margin_nok_v1(precheck(),side="Buy",account_currency="USD")


def test_saxo_trade_pnl_is_base_currency_and_net_of_explicit_costs():
    x=sample()
    assert x.mark_to_liquidate_nok==20.0
    assert x.position_key==POSITION.key
    assert inspect_open_position_v1(
        position=POSITION,sample=x,state=None,now=NOW).pnl_pct==2.0


@pytest.mark.parametrize("field,value",[
    ("PositionsAccount","other"),
    ("Uic",12346),
    ("AssetType","Stock"),
    ("AmountLong",.02),
])
def test_wrong_account_instrument_or_quantity_is_blocked(field,value):
    row=netposition()
    row["NetPositionBase"][field]=value
    with pytest.raises(ValueError):
        sample(row)


@pytest.mark.parametrize("field,value",[
    ("ProfitLossOnTradeInBaseCurrency",None),
    ("TradeCostsTotalInBaseCurrency",None),
    ("CurrentPriceLastTraded",None),
    ("CalculationReliability",None),
    ("CurrentPriceDelayMinutes",None),
])
def test_missing_broker_fields_are_not_defaulted_to_zero(field,value):
    row=netposition()
    row["NetPositionView"][field]=value
    with pytest.raises((ValueError,TypeError)):
        sample(row)


def test_broker_quote_must_be_fresh_for_a_stop():
    row=netposition()
    row["NetPositionView"]["CurrentPriceLastTraded"]=(NOW-timedelta(minutes=1)).isoformat()
    x=sample(row)
    assert inspect_open_position_v1(
        position=POSITION,sample=x,state=None,now=NOW).action=="BLOCKED"


def test_broker_delayed_flag_must_block_stop_claim():
    row=netposition()
    row["NetPositionView"]["CurrentPriceDelayMinutes"]=15
    x=sample(row)
    assert inspect_open_position_v1(
        position=POSITION,sample=x,state=None,now=NOW).action=="BLOCKED"


def test_net_position_id_and_proven_base_currency_required():
    row=netposition()
    row["NetPositionId"]="DIFFERENT_POSITION"
    with pytest.raises(ValueError):
        sample(row)
    row=netposition()
    with pytest.raises(ValueError):
        validated_saxo_pnl_v1(
            row=row,position=POSITION,account_currency="NOK",
            verified_base_currency="USD",estimated_exit_cost_nok=3,received_at=NOW)


def test_estimated_extra_exit_costs_must_not_be_guessed_or_double_counted():
    with pytest.raises(ValueError):
        sample(extra=-1)
    with pytest.raises(ValueError):
        sample(extra=float("nan"))
    # Explicit zero only when Saxo's TradeCostsTotal already includes full exit.
    assert sample(extra=0).mark_to_liquidate_nok==23.0
