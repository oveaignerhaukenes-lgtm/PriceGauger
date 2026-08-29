from __future__ import annotations

import pytest

from autotrader_closed_position_reconciliation_v2 import (
    closed_position_realizations_v2,
    match_close_realizations_v2,
    realized_net_pnl_v2,
)


def _row(
    unique_id: str,
    *,
    amount: float,
    gross: float,
    open_cost: float,
    close_cost: float,
    reference: str = "pg-close-abc",
    account_id: str = "ACC-1",
    uic: int = 12345,
    asset_type: str = "CfdOnIndex",
):
    return {
        "ClosedPositionUniqueId": unique_id,
        "NetPositionId": "NET-1",
        "ClosedPosition": {
            "AccountId": account_id,
            "Amount": amount,
            "AssetType": asset_type,
            "Uic": uic,
            "ClosingExternalReferenceId": reference,
            "ClosingPositionId": f"close-{unique_id}",
            "ClosedProfitLossInBaseCurrency": gross,
            "CostOpeningInBaseCurrency": open_cost,
            "CostClosingInBaseCurrency": close_cost,
            "ExecutionTimeClose": "2026-08-29T08:00:00Z",
        },
    }


def test_parser_and_net_pnl_deduct_costs_regardless_of_cost_sign():
    payload = {
        "Data": [
            _row("1", amount=3.0, gross=100.0, open_cost=-2.0, close_cost=3.0),
            _row("2", amount=2.0, gross=20.0, open_cost=1.0, close_cost=-1.0),
        ]
    }
    items = closed_position_realizations_v2(payload)
    assert len(items) == 2
    assert realized_net_pnl_v2(items) == pytest.approx(113.0)


def test_split_close_is_matched_only_when_full_expected_amount_is_present():
    first = closed_position_realizations_v2(
        {"Data": [_row("1", amount=3.0, gross=10.0, open_cost=0.0, close_cost=0.0)]}
    )
    assert match_close_realizations_v2(
        realizations=first,
        account_id="ACC-1",
        uic=12345,
        asset_type="CfdOnIndex",
        external_reference="pg-close-abc",
        expected_amount=5.0,
    ) == ()

    complete = closed_position_realizations_v2(
        {
            "Data": [
                _row("1", amount=3.0, gross=10.0, open_cost=0.0, close_cost=0.0),
                _row("2", amount=2.0, gross=5.0, open_cost=0.0, close_cost=0.0),
            ]
        }
    )
    matched = match_close_realizations_v2(
        realizations=complete,
        account_id="ACC-1",
        uic=12345,
        asset_type="CfdOnIndex",
        external_reference="pg-close-abc",
        expected_amount=5.0,
    )
    assert len(matched) == 2
    assert sum(item.amount for item in matched) == pytest.approx(5.0)


def test_external_reference_and_exact_product_identity_are_mandatory():
    items = closed_position_realizations_v2(
        {"Data": [_row("1", amount=5.0, gross=10.0, open_cost=0.0, close_cost=0.0)]}
    )
    for account_id, uic, asset_type, reference in (
        ("ACC-X", 12345, "CfdOnIndex", "pg-close-abc"),
        ("ACC-1", 999, "CfdOnIndex", "pg-close-abc"),
        ("ACC-1", 12345, "Stock", "pg-close-abc"),
        ("ACC-1", 12345, "CfdOnIndex", "other-reference"),
    ):
        assert match_close_realizations_v2(
            realizations=items,
            account_id=account_id,
            uic=uic,
            asset_type=asset_type,
            external_reference=reference,
            expected_amount=5.0,
        ) == ()


def test_missing_authoritative_base_currency_pnl_fails_closed():
    row = _row("1", amount=1.0, gross=5.0, open_cost=0.0, close_cost=0.0)
    row["ClosedPosition"].pop("ClosedProfitLossInBaseCurrency")
    with pytest.raises(ValueError, match="ClosedProfitLossInBaseCurrency"):
        closed_position_realizations_v2({"Data": [row]})
