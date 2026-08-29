from __future__ import annotations

from datetime import datetime, timezone

import pytest

import autotrader_closed_position_reconciliation_v2 as reconciliation_v2
from autotrader_closed_position_reconciliation_v2 import (
    RISK_REENTRY_BLOCK_REASON,
    closed_position_realizations_v2,
    invalidate_stale_reentry_after_risk_close_v2,
    match_close_realizations_v2,
    realized_net_pnl_v2,
    risk_flat_since_v2,
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
    execution_time_close: str | None = "2026-08-29T08:00:00Z",
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
            "ExecutionTimeClose": execution_time_close,
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


def test_risk_flat_since_uses_latest_execution_in_split_close():
    items = closed_position_realizations_v2(
        {
            "Data": [
                _row(
                    "1",
                    amount=3.0,
                    gross=10.0,
                    open_cost=0.0,
                    close_cost=0.0,
                    execution_time_close="2026-08-29T08:00:00Z",
                ),
                _row(
                    "2",
                    amount=2.0,
                    gross=5.0,
                    open_cost=0.0,
                    close_cost=0.0,
                    execution_time_close="2026-08-29T08:00:02Z",
                ),
            ]
        }
    )
    assert risk_flat_since_v2(items) == datetime(2026, 8, 29, 8, 0, 2, tzinfo=timezone.utc)


def test_missing_close_execution_time_fails_conservatively_to_no_boundary():
    items = closed_position_realizations_v2(
        {
            "Data": [
                _row(
                    "1",
                    amount=1.0,
                    gross=5.0,
                    open_cost=0.0,
                    close_cost=0.0,
                    execution_time_close=None,
                )
            ]
        }
    )
    assert risk_flat_since_v2(items) is None


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDb:
    def __init__(self, risk_event):
        self.risk_event = risk_event
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.calls.append((normalized, tuple(params)))
        if normalized.startswith("SELECT reason FROM pg_v2_autotrader_risk_events"):
            return _FakeResult(self.risk_event)
        return _FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_risk_origin_close_supersedes_only_signals_at_or_before_flat(monkeypatch):
    db = _FakeDb({"reason": "HARD_STOP"})
    monkeypatch.setattr(reconciliation_v2, "connect", lambda: db)
    flat_since = datetime(2026, 8, 29, 8, 0, 2, tzinfo=timezone.utc)

    assert invalidate_stale_reentry_after_risk_close_v2(
        close_event_id="risk-event-1",
        pilot_key="pilot-1",
        flat_since=flat_since,
    ) is True

    request_update = next(call for call in db.calls if "UPDATE pg_v2_autotrader_execution_requests" in call[0])
    assert "signal_at <= ?" in request_update[0]
    assert request_update[1] == (RISK_REENTRY_BLOCK_REASON, "pilot-1", flat_since)

    state_update = next(call for call in db.calls if "UPDATE pg_v2_autotrader_strategy_runtime_state" in call[0])
    assert "pending_signal_at <= ?" in state_update[0]
    assert state_update[1] == ("pilot-1", flat_since)


def test_strategy_origin_close_does_not_invalidate_pending_reversal(monkeypatch):
    db = _FakeDb(None)
    monkeypatch.setattr(reconciliation_v2, "connect", lambda: db)

    assert invalidate_stale_reentry_after_risk_close_v2(
        close_event_id="strategy-request-1",
        pilot_key="pilot-1",
        flat_since=datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
    ) is False
    assert len(db.calls) == 1
    assert db.calls[0][0].startswith("SELECT reason FROM pg_v2_autotrader_risk_events")
