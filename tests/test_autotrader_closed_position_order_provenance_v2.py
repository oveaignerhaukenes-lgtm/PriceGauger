from __future__ import annotations

import autotrader_closed_position_reconciliation_v2 as reconciliation_v2
from autotrader_closed_position_reconciliation_v2 import (
    closed_position_realizations_v2,
    match_close_realizations_v2,
)


def _row(
    unique_id: str,
    *,
    amount: float = 0.01,
    reference: str | None = None,
    closing_position_id: str = "POS-CLOSE-1",
    account_id: str = "ACC-1",
    uic: int = 4912,
    asset_type: str = "CfdOnIndex",
):
    closed = {
        "AccountId": account_id,
        "Amount": amount,
        "AssetType": asset_type,
        "Uic": uic,
        "ClosingPositionId": closing_position_id,
        "ClosedProfitLossInBaseCurrency": 3.0,
        "CostOpeningInBaseCurrency": 0.0,
        "CostClosingInBaseCurrency": 0.0,
        "ExecutionTimeClose": "2026-09-02T05:00:00Z",
    }
    if reference is not None:
        closed["ClosingExternalReferenceId"] = reference
    return {
        "ClosedPositionUniqueId": unique_id,
        "ClosedPosition": closed,
    }


def test_closed_position_without_external_reference_is_retained_for_exact_order_fallback():
    items = closed_position_realizations_v2({"Data": [_row("closed-1")]})
    assert len(items) == 1
    assert items[0].closing_external_reference == ""
    assert items[0].closing_position_id == "POS-CLOSE-1"


def test_exact_order_position_id_fallback_matches_missing_external_reference():
    items = closed_position_realizations_v2(
        {
            "Data": [
                _row("closed-1", amount=0.01, closing_position_id="POS-CLOSE-1"),
                _row("closed-other", amount=0.02, closing_position_id="UNRELATED"),
            ]
        }
    )
    matched = match_close_realizations_v2(
        realizations=items,
        account_id="ACC-1",
        uic=4912,
        asset_type="CfdOnIndex",
        external_reference="pg-strategy-close-request",
        expected_amount=0.01,
        closing_position_ids=frozenset({"POS-CLOSE-1"}),
    )
    assert tuple(item.unique_id for item in matched) == ("closed-1",)


def test_order_position_id_fallback_still_requires_exact_product_and_full_amount():
    items = closed_position_realizations_v2(
        {"Data": [_row("closed-1", amount=0.005, closing_position_id="POS-CLOSE-1")]}
    )
    assert match_close_realizations_v2(
        realizations=items,
        account_id="ACC-1",
        uic=4912,
        asset_type="CfdOnIndex",
        external_reference="missing",
        expected_amount=0.01,
        closing_position_ids=frozenset({"POS-CLOSE-1"}),
    ) == ()
    assert match_close_realizations_v2(
        realizations=items,
        account_id="ACC-1",
        uic=9999,
        asset_type="CfdOnIndex",
        external_reference="missing",
        expected_amount=0.005,
        closing_position_ids=frozenset({"POS-CLOSE-1"}),
    ) == ()


class _Client:
    def __init__(self):
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return {
            "Data": [
                {
                    "OrderId": "ORDER-1",
                    "Status": "Placed",
                    "SubStatus": "Confirmed",
                },
                {
                    "OrderId": "OTHER",
                    "Status": "FinalFill",
                    "SubStatus": "Confirmed",
                    "PositionId": "WRONG",
                },
                {
                    "OrderId": "ORDER-1",
                    "Status": "Fill",
                    "SubStatus": "Confirmed",
                    "PositionId": "POS-PARTIAL",
                },
                {
                    "OrderId": "ORDER-1",
                    "Status": "FinalFill",
                    "SubStatus": "Confirmed",
                    "PositionId": "POS-FINAL",
                },
            ]
        }


def test_order_activity_lookup_uses_exact_order_id_and_confirmed_fill_position_ids():
    client = _Client()
    ids = reconciliation_v2._order_fill_position_ids_v2(
        client,
        account_key="ACCOUNT-KEY",
        client_key="CLIENT-KEY",
        order_id="ORDER-1",
    )
    assert ids == frozenset({"POS-PARTIAL", "POS-FINAL"})
    assert client.calls == [
        (
            "cs/v1/audit/orderactivities",
            {
                "AccountKey": "ACCOUNT-KEY",
                "ClientKey": "CLIENT-KEY",
                "OrderId": "ORDER-1",
                "EntryType": "All",
                "$top": 1000,
            },
        )
    ]
