"""Historical Saxo order audit is exact-boundary and strictly read-only."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from saxo_provider import LIVE_BASE_URL
from saxo_trading import SaxoTradingSafetyError
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3


class FakeSaxo:
    base_url=LIVE_BASE_URL

    def __init__(self, entry, *, next_page=None):
        self.entry=entry
        self.next_page=next_page
        self.calls=[]

    def _get(self, endpoint, params=None):
        self.calls.append((endpoint, deepcopy(params)))
        if endpoint=="port/v1/accounts/me":
            return {"Data":[
                {"AccountId":"TECH-C","AccountKey":"private-account-key","ClientKey":"private-client-key"},
                {"AccountId":"TECH-D","AccountKey":"other-key","ClientKey":"other-client-key"},
            ]}
        assert endpoint=="cs/v1/audit/orderactivities"
        return {"Data":[] if self.entry is None else [self.entry],
                **({"__next":self.next_page} if self.next_page else {})}


def order_entry(**overrides):
    row={"OrderId":"50955547","AccountId":"TECH-C","Uic":4912,
         "AssetType":"CfdOnIndex","Status":"FinalFill",
         "SubStatus":"Confirmed","Amount":0.02,"FilledAmount":0.02,
         "BuySell":"Buy","ActivityTime":"2026-10-09T11:36:01Z"}
    row.update(overrides)
    return row


def audit(client):
    return client.order_activity_exact(
        account_id="TECH-C",order_id="50955547",uic=4912,asset_type="CfdOnIndex")


def test_exact_audit_returns_real_status_and_uses_only_get():
    fake=FakeSaxo(order_entry())
    result=audit(SaxoLivePilotClientV3(fake))
    assert result["status"]=="FinalFill"
    assert result["filled_amount"]==0.02
    assert result["order_id_suffix"]=="50955547"
    assert fake.calls[1]==(
        "cs/v1/audit/orderactivities",
        {"AccountKey":"private-account-key","OrderId":"50955547",
         "EntryType":"Last","$top":20},
    )
    assert all(not ep.startswith("trade/v2/orders") for ep,_ in fake.calls)


@pytest.mark.parametrize("override", [
    {"OrderId":"WRONG"},{"AccountId":"TECH-D"},
    {"AccountId":None},{"Uic":23},{"AssetType":"CfdOnStock"},
])
def test_audit_never_conflates_account_product_or_order(override):
    with pytest.raises(SaxoTradingSafetyError):
        audit(SaxoLivePilotClientV3(FakeSaxo(order_entry(**override))))


def test_empty_or_paginated_audit_is_unknown_not_a_terminal_proof():
    assert audit(SaxoLivePilotClientV3(FakeSaxo(None)))=={
        "available":False,"reason":"NO_ORDER_ACTIVITY"}
    with pytest.raises(SaxoTradingSafetyError):
        audit(SaxoLivePilotClientV3(FakeSaxo(order_entry(),next_page="/next")))


def test_same_order_can_have_cancelled_or_working_status_without_automatic_release():
    for state in ("Working","Cancelled","Expired","FinalFill"):
        result=audit(SaxoLivePilotClientV3(FakeSaxo(order_entry(Status=state))))
        assert result["status"]==state
    source=(Path(__file__).resolve().parent.parent / "autotrader_v3_live_runtime_v1.py").read_text()
    part=source[source.index("elif reconciliation.state=='WAIT':"):source.index(
        "else:",source.index("elif reconciliation.state=='WAIT':"))]
    assert "broker.order_activity_exact(" in part
    assert "action=READ_ONLY_KEEP_PENDING" in part
    assert "mark_order_v3(" not in part
    assert "no retry sent" in part


def test_audit_incorrect_response_type_fails_closed():
    class Malformed(FakeSaxo):
        def _get(self,endpoint,params=None):
            if endpoint=="port/v1/accounts/me":
                return super()._get(endpoint,params)
            return {"Data":None}
    with pytest.raises(SaxoTradingSafetyError):
        audit(SaxoLivePilotClientV3(Malformed(order_entry())))
