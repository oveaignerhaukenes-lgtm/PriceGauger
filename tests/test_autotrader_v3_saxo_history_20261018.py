from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from autotrader_v3_saxo_history_v1 import (
    normalize_timeseries_v1, normalize_transactions_v1, normalize_positions_v1,
    sync_account_v1, load_saxo_history_stats_v1,
)


def test_nav_change_does_not_masquerade_as_realized_trade_pnl():
    rows = normalize_timeseries_v1({
        "Balance": {
            "AccountValue": [
                {"Date": "2026-10-14", "Value": 1000},
                {"Date": "2026-10-15", "Value": 1130},
                {"Date": "2026-10-16", "Value": 1080},
            ],
            "CashTransfer": [{"Date": "2026-10-15", "Value": 100}],
        },
        "TimeWeighted": {"Accumulated": [
            {"Date": "2026-10-14", "Value": 0.01},
            {"Date": "2026-10-15", "Value": 0.04},
            {"Date": "2026-10-16", "Value": -0.01},
        ]},
    })
    assert rows[0]["nav_change_ex_cash"] is None
    assert rows[1]["nav_change_ex_cash"] == 30
    assert rows[2]["nav_change_ex_cash"] == -50
    assert rows[1]["daily_twr"] == pytest.approx((1.04/1.01)-1)
    assert rows[2]["daily_twr"] == pytest.approx((0.99/1.04)-1)


def test_broker_boundary_mismatch_rejected():
    with pytest.raises(ValueError, match="boundary"):
        normalize_transactions_v1(
            [{"AccountId": "other", "Date": "2026-10-15", "TradeId": "1"}], "A"
        )
    with pytest.raises(ValueError, match="boundary"):
        normalize_positions_v1(
            [{"AccountId": "other", "ExecutionTimeClose": "2026-10-15"}], "A"
        )


class FakeClient:
    def __init__(self):
        self.calls = []

    def _get(self, path, *, params):
        self.calls.append((path,params))
        assert params.get("AccountKey", params.get("AccountKeys")) == "a-key"
        assert params.get("ClientKey", "c-key") == "c-key"
        if path == "hist/v4/performance/timeseries":
            return {"Balance": {
                "AccountValue": [
                    {"Date":"2026-10-14","Value":1000},
                    {"Date":"2026-10-15","Value":1050},
                ],
                "CashTransfer": [],
            }, "TimeWeighted":{"Accumulated":[
                {"Date":"2026-10-14","Value":0},
                {"Date":"2026-10-15","Value":0.05},
            ]}}
        if path == "hist/v1/transactions":
            return {"Data":[{
                "AccountId":"A","Date":"2026-10-15","TradeId":"deal-1",
                "TransactionType":"Trade","RealizedPnL":40,
                "TotalCost":2.5,"Currency":"NOK",
            }]}
        if path == "hist/v3/positions/c-key":
            return {"Data":[{
                "AccountId":"A","PositionId":"p-1","Uic":"11",
                "ExecutionTimeClose":"2026-10-15T20:00:00Z",
                "ExecutionTimeOpen":"2026-10-15T19:00:00Z",
                "ProfitLoss":40,
            }]}
        raise AssertionError(path)


def test_sync_is_idempotent_and_uses_only_broker_get(tmp_path):
    client = FakeClient()
    broker = SimpleNamespace(client=client)
    path = str(tmp_path / "test_history.db")
    account = {"AccountId":"A","AccountKey":"a-key",
               "ClientKey":"c-key","Currency":"NOK"}
    for _ in range(2):
        assert sync_account_v1(
            broker=broker,account=account,from_day=date(2026,10,14),
            through_day=date(2026,10,16),db_path=path
        ) == (2,1,1)
    stats = load_saxo_history_stats_v1(db_path=path,from_day=date(2026,10,14))
    assert len(stats["days"]) == 2
    assert len(stats["transactions"]) == 1
    assert len(stats["closed_positions"]) == 1
    assert stats["days"][0]["day"] == "2026-10-15"
    assert stats["days"][0]["nav_change_ex_cash"] == 50
    assert stats["transactions"][0]["realized_pnl"] == 40
    assert [p for p,_ in client.calls].count("hist/v4/performance/timeseries") == 2


def test_incomplete_historical_response_cannot_persist_partial_rows(tmp_path):
    class Broken(FakeClient):
        def _get(self, path, *, params):
            if path == "hist/v3/positions/c-key":
                return {"BadEnvelope": []}
            return super()._get(path,params=params)

    path = str(tmp_path / "partial.db")
    with pytest.raises(ValueError,match="Data"):
        sync_account_v1(
            broker=SimpleNamespace(client=Broken()),
            account={"AccountId":"A","AccountKey":"a-key","ClientKey":"c-key"},
            from_day=date(2026,10,14),through_day=date(2026,10,16),
            db_path=path,
        )
    assert not __import__("os").path.exists(path)


def test_missing_points_are_not_zero_and_bad_amounts_fail_closed():
    with pytest.raises(ValueError,match="empty"):
        normalize_timeseries_v1({"Balance":{"AccountValue":[]}})
    with pytest.raises(ValueError,match="invalid"):
        normalize_timeseries_v1({"Balance":{"AccountValue":[
            {"Date":"2026-10-14","Value":float("nan")}
        ]}})
