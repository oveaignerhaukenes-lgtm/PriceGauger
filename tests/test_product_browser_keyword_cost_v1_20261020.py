"""Saxo keyword Product Browser: minimum incremental NOK and fee evidence."""
from math import isclose
from pathlib import Path
import pytest

from product_browser_keyword_cost_v1 import (
    KeywordCostFilterV1, FEE_ANY,FEE_FIXED,FEE_VARIABLE,FEE_UNKNOWN,
    FEE_ZERO,FEE_MIXED,
    search_keyword_cost_products_v1,cost_model_from_two_sizes_v1,
    product_matches_filters_v1,keyword_cost_rows_v1,
)
from saxo_low_friction_candidates_v2 import LowFrictionAccountV2


class FakeSaxoCatalog:
    base_url="https://gateway.saxobank.com/sim/openapi"

    def __init__(self, *,missing_commissions=False,no_fx=False):
        self.calls=[]
        self.missing_commissions=missing_commissions
        self.no_fx=no_fx

    def _get(self,path,*,params=None):
        self.calls.append((path,params or {}))
        if path=="ref/v1/instruments":
            word=params.get("Keywords","")
            if word=="Gold":
                return {"Data":[
                    {"Identifier":1001,"AssetType":"CfdOnFutures",
                     "Description":"Gold CFD","Symbol":"GOLD",
                     "CurrencyCode":"USD"},
                    {"Identifier":1002,"AssetType":"ContractFutures",
                     "Description":"Gold Futures Unknown Multiplier",
                     "Symbol":"GOLDFUT","CurrencyCode":"USD"},
                    {"Identifier":1003,"AssetType":"Stock",
                     "Description":"Goldman Sachs","Symbol":"GS",
                     "CurrencyCode":"USD"},
                ]}
            return {"Data":[]}
        if path=="ref/v1/instruments/details/1001/CfdOnFutures":
            return {"Uic":1001,"PriceCurrency":"USD",
                    "MinimumTradeSize":.01,"IncrementSize":.005,
                    "ContractSize":1}
        if path=="ref/v1/instruments/details/1002/ContractFutures":
            return {"Uic":1002,"PriceCurrency":"USD",
                    "MinimumTradeSize":1,"IncrementSize":1}
        if path=="ref/v1/instruments/details/1003/Stock":
            return {"Uic":1003,"PriceCurrency":"USD",
                    "MinimumTradeSize":1,"IncrementSize":1}
        if path.startswith("cs/v1/tradingconditions/cost/"):
            amount=float(params["Amount"])
            if "/1001/" in path:
                fee=amount*100  # .01 -> 1, .02 -> 2 : variable
            else:
                fee=15
            def side():
                tc={} if self.missing_commissions else {
                    "Commissions":[{"Value":fee}]}
                return {"Currency":"NOK","TradingCost":tc,"TotalCostPct":.12}
            return {"Cost":{"Long":side(),"Short":side()},
                    "AccountCurrency":"NOK"}
        raise AssertionError("unexpected Saxo GET: "+path)

    def search_instruments(self,keywords,*,asset_types):
        self.calls.append(("search_instruments",{"keywords":keywords}))
        if keywords=="USDNOK" and not self.no_fx:
            from saxo_provider import SaxoInstrument
            return [SaxoInstrument(
                asset="fx",uic=500,asset_type="FxSpot",
                symbol="USDNOK",description="USD/NOK",
            )]
        return []

    def info_price(self,instrument):
        self.calls.append(("info_price",{"uic":instrument.uic}))
        if instrument.uic==500:
            return {"Quote":{"Bid":9.99,"Ask":10.01}}
        if instrument.uic==1001:
            return {"Quote":{"Bid":1999.,"Ask":2001.}}
        if instrument.uic==1002:
            return {"Quote":{"Bid":2000.,"Ask":2002.}}
        return {"Quote":{"Bid":100.,"Ask":100.5}}


ACCOUNT=LowFrictionAccountV2(account_key="account-key",
                            account_id="123456INET",currency="NOK")


def search(**kwargs):
    return search_keyword_cost_products_v1(
        FakeSaxoCatalog(),KeywordCostFilterV1(
            keywords="Gold",max_inspections=3,account_key=ACCOUNT.account_key,
            **kwargs),account=ACCOUNT)


def test_gold_cfd_exact_nok_increment_and_proportional_commission():
    result=search(max_increment_nok=120,fee_model=FEE_VARIABLE)
    assert result.raw_count==3
    assert result.inspected_count==3
    assert len(result.products)==1
    gold=result.products[0]
    assert gold.product.instrument.uic==1001
    assert gold.trade_step==.005
    assert isclose(gold.step_nok,100.,abs_tol=1e-9)
    assert isclose(gold.minimum_initial_nok,200.,abs_tol=1e-9)
    assert gold.commission_model=="VARIABLE"
    assert gold.commission_currency=="NOK"
    assert gold.verification=="INDIKATIV – precheck kreves"
    assert keyword_cost_rows_v1(result.products)[0]["AutoTrader LIVE-godkjent"].startswith("Nei")


def test_no_fx_never_assumes_one_to_one_nok():
    client=FakeSaxoCatalog(no_fx=True)
    opts=KeywordCostFilterV1(keywords="Gold",max_increment_nok=100,
                            max_inspections=1,account_key=ACCOUNT.account_key)
    rows=search_keyword_cost_products_v1(client,opts,account=ACCOUNT)
    assert rows.products[0].step_nok is None
    assert rows.products[0].fx_source.startswith("Ingen verifisert")
    assert not search_keyword_cost_products_v1(
        FakeSaxoCatalog(no_fx=True),
        KeywordCostFilterV1(keywords="Gold",max_increment_nok=100,
                            max_inspections=1,account_key=ACCOUNT.account_key,
                            include_unknown_increment=False),account=ACCOUNT).products


def test_missing_commissions_never_becomes_free():
    rows=search_keyword_cost_products_v1(
        FakeSaxoCatalog(missing_commissions=True),
        KeywordCostFilterV1(keywords="Gold",max_inspections=1,
                            account_key=ACCOUNT.account_key),account=ACCOUNT,
    )
    assert rows.products[0].commission_model=="UNKNOWN"
    assert rows.products[0].long_commission is None
    assert not search_keyword_cost_products_v1(
        FakeSaxoCatalog(missing_commissions=True),
        KeywordCostFilterV1(keywords="Gold",max_inspections=1,
                            account_key=ACCOUNT.account_key,fee_model=FEE_ZERO),
        account=ACCOUNT).products


def test_futures_without_contract_multiplier_never_get_fictitious_nok_size():
    rows=search(max_increment_nok=50000)
    future=next(x for x in rows.products if x.product.instrument.uic==1002)
    assert future.step_nok is None
    assert "Kontraktstørrelse mangler" in " ".join(future.notes)
    assert next(x for x in rows.products if x.product.instrument.uic==1001).step_nok==100.


def test_fixed_variable_mixed_zero_ambiguous():
    assert cost_model_from_two_sizes_v1((0,0),(0,0))=="ZERO"
    assert cost_model_from_two_sizes_v1((10,10),(10,10))=="FIXED"
    assert cost_model_from_two_sizes_v1((10,10),(20,20))=="VARIABLE"
    assert cost_model_from_two_sizes_v1((10,10),(16,16))=="MIXED"
    assert cost_model_from_two_sizes_v1((None,0),(0,0))=="UNKNOWN"
    assert cost_model_from_two_sizes_v1((10,10),(5,9))=="UNKNOWN"


def test_account_scoping_and_boundaries():
    with pytest.raises(ValueError,match="AccountKey"):
        search_keyword_cost_products_v1(
            FakeSaxoCatalog(),
            KeywordCostFilterV1(keywords="Gold",account_key="other"),
            account=ACCOUNT)
    with pytest.raises(ValueError,match="120"):
        KeywordCostFilterV1(keywords="x"*121)
    with pytest.raises(ValueError,match="positiv"):
        KeywordCostFilterV1(keywords="Gold",max_increment_nok=0)
    with pytest.raises(ValueError,match="1–30"):
        KeywordCostFilterV1(keywords="Gold",max_inspections=50)


def test_integration_is_read_only_and_visible_first():
    main=Path("pages/1_Product_Browser.py").read_text()
    ui=Path("product_browser_keyword_cost_ui_v1.py").read_text()
    src=Path("product_browser_keyword_cost_v1.py").read_text()
    assert 'Fritekst + NOK/kurtasje' in main
    assert "with keyword_tab:" in main
    assert "render_keyword_cost_browser_v1()" in main
    assert "Søkeord" in ui and "Søk og sammenlign" in ui
    assert "Maks. minste handelstrinn (NOK)" in ui
    assert "Kurtasjemodell" in ui
    assert "Saxo-konto for kostnader" in ui
    assert "precheck" in ui.lower()
    for excluded in ("place_order(","_post(", "confirm_live=True",
                     "onboard_saxo_instrument_v2(", "set_live_authority_v3("):
        assert excluded not in src
        assert excluded not in ui
