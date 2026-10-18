"""Read-only metadata diagnostics for blocked Saxo futures family proof."""
from __future__ import annotations
import logging
from datetime import datetime,timezone

import futures_rollover_discovery_v2 as discovery
import futures_rollover_v1 as rollover
from instrument_registry_v2 import InstrumentSourceV2

SRC=InstrumentSourceV2(
    market_id=7,market_name="Natural Gas",instrument_id=99,
    instrument_type="future",display_name="Henry Hub Natural Gas",
    provider="saxo",provider_instrument_id="50419383",
    asset_type="ContractFutures",symbol="NGU6",price_multiplier=1.,
    metadata={"description":"Henry Hub Natural Gas - Sep 2026",
              "expiry":"2026-08-27T18:30:00Z"},
)


class Broker:
    def __init__(self):
        self.calls=[]
    def instrument_details(self,instrument):
        self.calls.append(("GET_DETAILS",instrument.uic))
        if instrument.uic==50419383:
            return {"Uic":50419383,"AssetType":"ContractFutures",
                    "Symbol":"NGU6","Description":"Henry Hub Natural Gas - Sep 2026",
                    "IsTradable":False,"GroupId":None,
                    "Exchange":{"ExchangeId":"NYMEX"},
                    "ExpiryDateTime":"2026-08-27T18:30:00Z"}
        return {"Uic":51202678,"AssetType":"ContractFutures",
                "Symbol":"NGX6","Description":"Henry Hub Natural Gas - Nov 2026",
                "IsTradable":True,"CurrencyCode":"USD",
                "Exchange":{"ExchangeId":"NYMEX"},
                "GroupId":173,"ContractSize":10000,
                "ExpiryDateTime":"2026-10-28T18:30:00Z"}
    def _get(self,path,params=None):
        self.calls.append(("GET_REFERENCE",params))
        if "Uics" in params:return {"Data":[]}
        return {"Data":[
            {"Identifier":51202678,"Symbol":"NGX6","GroupId":173,
             "AssetType":"ContractFutures","PrimaryListing":51202678,
             "ExchangeId":"NYMEX","Description":"Henry Hub Natural Gas - Nov 2026"},
            {"Identifier":52477959,"Symbol":"NGZ6","GroupId":173,
             "AssetType":"ContractFutures","PrimaryListing":51202678,
             "ExchangeId":"NYMEX","Description":"Henry Hub Natural Gas - Dec 2026"}
        ]}
    def _post(self,*args,**kw):
        raise AssertionError("no POST in futures evidence")
    def place_order(self,*args,**kw):
        raise AssertionError("no order in futures evidence")


def test_missing_old_group_returns_public_broker_metadata_without_switch(monkeypatch,caplog):
    monkeypatch.setattr(rollover,"list_subscribed_sources_v2",lambda provider=None:(SRC,))
    monkeypatch.setattr(rollover,"_apply_rollover",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("No unproven switch")))
    b=Broker()
    with caplog.at_level(logging.WARNING):
        result=discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
            client=b,now=datetime(2026,10,18,tzinfo=timezone.utc))
    assert result.rolled==0 and result.failed==1
    assert "family evidence READ_ONLY" in caplog.text
    assert "old_uic=50419383" in caplog.text
    assert "broker_primary=51202678" in caplog.text
    assert "'group_id': 173" in caplog.text
    assert "front=" in caplog.text
    assert all(c[0].startswith("GET") for c in b.calls)


def test_public_identity_has_no_account_or_pnl_fields():
    response={"Uic":51202678,"AssetType":"ContractFutures","GroupId":173,
              "AccountKey":"TOP_SECRET","ProfitLossOnTradeInBaseCurrency":999,
              "Exchange":{"ExchangeId":"NYMEX"}}
    output=discovery._public_saxo_instrument_identity_v3(response)
    assert "TOP_SECRET" not in str(output)
    assert "999" not in str(output)
    assert output["group_id"]==173
