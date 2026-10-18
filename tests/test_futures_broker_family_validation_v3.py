"""Only proven Saxo NG futures-family continuity can permit collection rollover."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime,timezone

import pytest

import futures_rollover_discovery_v2 as discovery
import futures_rollover_v1 as rollover
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument

NOW=datetime(2026,10,18,tzinfo=timezone.utc)
OLD=SaxoInstrument(
    asset="Natural Gas",uic=50419383,asset_type="ContractFutures",
    symbol="NGU6",description="Henry Hub Natural Gas - Sep 2026",
)
SOURCE=InstrumentSourceV2(
    market_id=7,market_name="Natural Gas",instrument_id=99,
    instrument_type="future",display_name="Henry Hub Natural Gas",
    provider="saxo",provider_instrument_id="50419383",
    asset_type="ContractFutures",symbol="NGU6",price_multiplier=1.,
    metadata={"description":"Henry Hub Natural Gas - Sep 2026",
              "expiry":"2026-08-27T18:30:00Z"},
)
OLD_DETAILS={
    "Uic":50419383,"AssetType":"ContractFutures","Symbol":"NGU6",
    "Description":"Henry Hub Natural Gas - Sep 2026",
    "IsTradable":False,"ExpiryDateTime":"2026-08-27T18:30:00Z",
    "CurrencyCode":"USD","ContractSize":10000,"GroupId":173,
    "Exchange":{"ExchangeId":"NYMEX"},
}
NEW_DETAILS={
    "Uic":51202678,"AssetType":"ContractFutures","Symbol":"NGX6",
    "Description":"Henry Hub Natural Gas - Nov 2026",
    "IsTradable":True,"ExpiryDateTime":"2026-10-28T18:30:00Z",
    "CurrencyCode":"USD","ContractSize":10000,"GroupId":173,
    "Exchange":{"ExchangeId":"NYMEX"},
}
ROWS=[
    {"Identifier":51202678,"AssetType":"ContractFutures","Symbol":"NGX6",
     "Description":"Henry Hub Natural Gas - Nov 2026","ExchangeId":"NYMEX",
     "GroupId":173,"PrimaryListing":51202678},
    {"Identifier":52477959,"AssetType":"ContractFutures","Symbol":"NGZ6",
     "Description":"Henry Hub Natural Gas - Dec 2026","ExchangeId":"NYMEX",
     "GroupId":173,"PrimaryListing":51202678},
    {"Identifier":53236329,"AssetType":"ContractFutures","Symbol":"NGF7",
     "Description":"Henry Hub Natural Gas - Jan 2027","ExchangeId":"NYMEX",
     "GroupId":173,"PrimaryListing":51202678},
]


class ReadOnlyBroker:
    def __init__(self,*,old=None,new=None,rows=None):
        self.old=deepcopy(OLD_DETAILS if old is None else old)
        self.new=deepcopy(NEW_DETAILS if new is None else new)
        self.rows=deepcopy(ROWS if rows is None else rows)
        self.calls=[]
    def instrument_details(self,instrument):
        self.calls.append(("GET_DETAILS",instrument.uic))
        assert instrument.asset_type=="ContractFutures"
        if instrument.uic==50419383:return deepcopy(self.old)
        if instrument.uic==51202678:return deepcopy(self.new)
        raise AssertionError("Unapproved Saxo candidate GET")
    def _get(self,path,params=None):
        self.calls.append(("GET_REFERENCE",params))
        assert path=="ref/v1/instruments"
        assert params["IncludeNonTradable"] is True
        if "Uics" in params:return {"Data":[]}
        return {"Data":deepcopy(self.rows)}
    def _post(self,*a,**k):
        raise AssertionError("Read-only verification never posts")
    def place_order(self,*a,**k):
        raise AssertionError("Read-only verification never trades")


def test_broker_verified_family_can_roll_only_collection_identity(monkeypatch):
    b=ReadOnlyBroker()
    monkeypatch.setattr(rollover,"list_subscribed_sources_v2",
                        lambda provider=None:(SOURCE,))
    committed=[]
    monkeypatch.setattr(rollover,"_apply_rollover",
                        lambda **kw:committed.append(kw) or 100)
    summary=discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=b,now=NOW,
    )
    assert summary.rolled==1 and summary.failed==0
    assert len(committed)==1
    assert committed[0]["candidate"].uic==51202678
    assert all(c[0].startswith("GET") for c in b.calls)


@pytest.mark.parametrize("field,modified",[
    ("group",lambda b:b.old.update(GroupId=999)),
    ("exchange",lambda b:b.old.update(Exchange={"ExchangeId":"ICE"})),
    ("currency",lambda b:b.new.update(CurrencyCode="EUR")),
    ("contract_size",lambda b:b.new.update(ContractSize=1000)),
    ("old_contract_size",lambda b:b.old.pop("ContractSize")),
    ("new_expiry",lambda b:b.new.update(ExpiryDateTime="2026-09-01T00:00:00Z")),
    ("new_tradability",lambda b:b.new.update(IsTradable=False)),
    ("wrong_root",lambda b:b.rows[0].update(Symbol="CLX6")),
    ("wrong_group",lambda b:b.rows[1].update(GroupId=444)),
    ("unknown_old",lambda b:b.old.pop("Uic")),
    ("wrong_description",lambda b:b.new.update(Description="European Natural Gas - Nov 2026")),
    ("ambiguous_primary",lambda b:b.rows[1].update(PrimaryListing=52477959)),
    ("unknown_exchange",lambda b:b.old.pop("Exchange")),
])
def test_missing_or_contradictory_broker_identity_never_rolls(field,modified):
    broker=ReadOnlyBroker()
    modified(broker)
    chosen=discovery._same_family_successor_v3(
        broker,instrument=OLD,old_details=broker.old,
        rows=broker.rows,now=NOW,
    )
    assert chosen is None,field
    assert all(c[0].startswith("GET") for c in broker.calls)


def test_broker_summary_candidates_cannot_authorize_unrelated_root():
    old=deepcopy(OLD_DETAILS)
    result=discovery._same_family_successor_v3(
        ReadOnlyBroker(),instrument=SaxoInstrument(
            asset="Natural Gas",uic=50419383,asset_type="ContractFutures",
            symbol="TTFU6",description="European Natural Gas - Sep 2026"),
        old_details=old,rows=deepcopy(ROWS),now=NOW,
    )
    assert result is None


def test_lookup_is_not_wired_into_live_order_execution():
    from pathlib import Path
    source=Path("futures_rollover_discovery_v2.py").read_text()
    assert "autotrader_live_open" not in source
    assert "autotrader_live_close" not in source
    assert "place_order(" not in source
    assert "Saxo futures family VERIFIED" in source



def test_archived_old_group_missing_recovers_only_with_three_matching_broker_summaries(monkeypatch):
    b=ReadOnlyBroker()
    b.old.pop("GroupId")
    b.rows.append({
        "Identifier":888,"AssetType":"ContractFutures","Symbol":"TTFX6",
        "Description":"European Natural Gas - Nov 2026",
        "ExchangeId":"ICE","GroupId":999,"PrimaryListing":888,
    })
    monkeypatch.setattr(rollover,"list_subscribed_sources_v2",lambda provider=None:(SOURCE,))
    committed=[]
    monkeypatch.setattr(rollover,"_apply_rollover",
                        lambda **kw:committed.append(kw) or 100)
    result=discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=b,now=NOW,
    )
    assert result.rolled==1 and result.failed==0
    assert committed[0]["candidate"].uic==51202678
    assert all(x[0].startswith("GET") for x in b.calls)


def test_missing_old_group_requires_multiple_positive_consistent_broker_group_ids():
    b=ReadOnlyBroker()
    b.old.pop("GroupId")
    assert discovery._same_family_successor_v3(
        b,instrument=OLD,old_details=b.old,rows=b.rows,now=NOW
    )==51202678

    too_few=b.rows[:2]
    assert discovery._same_family_successor_v3(
        b,instrument=OLD,old_details=b.old,rows=too_few,now=NOW
    ) is None

    contradictory=deepcopy(b.rows)
    contradictory[1]["GroupId"]=999
    assert discovery._same_family_successor_v3(
        b,instrument=OLD,old_details=b.old,rows=contradictory,now=NOW
    ) is None

    group_missing=deepcopy(b.rows)
    group_missing[1].pop("GroupId")
    assert discovery._same_family_successor_v3(
        b,instrument=OLD,old_details=b.old,rows=group_missing,now=NOW
    ) is None


def test_missing_group_from_both_details_is_proven_by_broker_summary_consensus(monkeypatch):
    # Real Saxo: expired NGU6 AND current NGX6 DETAILS omit GroupId;
    # broker's multiple distinct summary rows agree on GroupId 39074.
    b=ReadOnlyBroker()
    b.old.pop("GroupId")
    b.new.pop("GroupId")
    for row in b.rows:
        row["GroupId"]=39074
    monkeypatch.setattr(rollover,"list_subscribed_sources_v2",lambda provider=None:(SOURCE,))
    collected=[]
    monkeypatch.setattr(rollover,"_apply_rollover",
                        lambda **kw:collected.append(kw) or 100)
    result=discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=b,now=NOW
    )
    assert result.rolled==1 and result.failed==0
    assert collected[0]["candidate"].uic==51202678
    assert all(call[0].startswith("GET") for call in b.calls)


@pytest.mark.parametrize("modified",[
    lambda b: b.new.update(GroupId=999),
    lambda b: b.new.update(ContractSize=5000),
    lambda b: b.new.update(CurrencyCode="EUR"),
    lambda b: b.new.update(Exchange={"ExchangeId":"ICE"}),
    lambda b: b.new.update(IsTradable=False),
    lambda b: b.new.update(ExpiryDateTime="2026-09-01T00:00:00Z"),
    lambda b: b.rows[1].update(GroupId=999),
    lambda b: b.rows[1].pop("GroupId"),
    lambda b: b.rows[2].update(PrimaryListing=52477959),
])
def test_missing_groups_never_override_an_actual_broker_contradiction(modified):
    b=ReadOnlyBroker()
    b.old.pop("GroupId")
    b.new.pop("GroupId")
    for row in b.rows:
        row["GroupId"]=39074
    modified(b)
    result=discovery._same_family_successor_v3(
        b,instrument=OLD,old_details=b.old,rows=b.rows,now=NOW
    )
    assert result is None
