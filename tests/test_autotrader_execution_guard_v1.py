from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_execution_guard_v1 as guard


class _Response:
    status_code = 204
    content = b""


class _Session:
    def __init__(self) -> None:
        self.calls = []

    def delete(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        return _Response()


class _Client:
    def __init__(self, payload=None) -> None:
        self.base_url = "https://gateway.saxobank.com/openapi"
        self.timeout = 20
        self.session = _Session()
        self.payload = payload or {}

    def _set_authorization(self, *, force_refresh=False):
        return None

    def _get(self, path, *, params=None):
        return self.payload


def test_stale_pg_cancel_uses_exact_order_id_and_account_key() -> None:
    client = _Client()
    guard._delete_order_once_v1(client, account_key="AK", order_id="12345")
    assert client.session.calls == [
        ("https://gateway.saxobank.com/openapi/trade/v2/orders/12345", {"AccountKey": "AK"}, 20)
    ]


def test_market_open_gate_requires_explicit_broker_true(monkeypatch) -> None:
    monkeypatch.setattr(guard, "_accounts", lambda client: ({"AK": "ACC"}, {"ACC": "AK"}))
    closed = _Client({"InstrumentPriceDetails": {"IsMarketOpen": False}, "Quote": {}})
    with pytest.raises(ValueError, match="SAXO_MARKET_NOT_EXPLICITLY_OPEN"):
        guard.require_market_open_for_open_v1(
            closed, account_id="ACC", uic=4912, asset_type="CfdOnIndex"
        )

    opened = _Client({"InstrumentPriceDetails": {"IsMarketOpen": True}, "Quote": {}})
    guard.require_market_open_for_open_v1(
        opened, account_id="ACC", uic=4912, asset_type="CfdOnIndex"
    )


def test_unknown_working_order_is_never_auto_cancelled(monkeypatch) -> None:
    enrollment = SimpleNamespace(pilot_key="p", uic=4912, asset_type="CfdOnIndex")
    monkeypatch.setattr(guard, "ensure_execution_guard_schema_v1", lambda: None)
    monkeypatch.setattr(guard, "_accounts", lambda client: ({"AK": "ACC"}, {"ACC": "AK"}))
    monkeypatch.setattr(
        guard,
        "_orders",
        lambda client: ({
            "AccountKey": "AK",
            "Uic": 4912,
            "AssetType": "CfdOnIndex",
            "OrderId": "manual",
            "ExternalReference": "",
        },),
    )
    monkeypatch.setattr(guard, "_enrollment", lambda *args, **kwargs: enrollment)
    monkeypatch.setattr(guard, "_anomaly", lambda *args, **kwargs: None)
    paused = []
    monkeypatch.setattr(guard, "_pause", lambda item, reason: paused.append((item, reason)))
    monkeypatch.setattr(
        guard,
        "_delete_order_once_v1",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("manual order must not be cancelled")
        ),
    )

    summary = guard.sweep_working_orders_v1(_Client())
    assert summary.unknown == 1
    assert summary.cancelled == 0
    assert paused and paused[0][0] is enrollment


def test_pg_close_order_is_left_to_close_executor(monkeypatch) -> None:
    monkeypatch.setattr(guard, "ensure_execution_guard_schema_v1", lambda: None)
    monkeypatch.setattr(guard, "_accounts", lambda client: ({"AK": "ACC"}, {"ACC": "AK"}))
    monkeypatch.setattr(
        guard,
        "_orders",
        lambda client: ({
            "AccountKey": "AK",
            "Uic": 4912,
            "AssetType": "CfdOnIndex",
            "OrderId": "close1",
            "ExternalReference": "pg-close-abc",
        },),
    )
    monkeypatch.setattr(guard, "_enrollment", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        guard,
        "_delete_order_once_v1",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("PG close order must not be cancelled here")
        ),
    )
    summary = guard.sweep_working_orders_v1(_Client())
    assert summary.pg_owned == 0
    assert summary.cancelled == 0


def test_facade_installs_guard_before_live_loop() -> None:
    source = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    assert "install_execution_safety_guard_v1()" in source
    assert source.index("install_execution_safety_guard_v1()") < source.index(
        "def run_live_open_forever_v2"
    )


def test_guard_covers_session_boundary_late_fill_and_auto_adoption() -> None:
    source = Path("autotrader_execution_guard_v1.py").read_text(encoding="utf-8")
    assert "IsMarketOpen" in source
    assert "STALE_PG_WORKING_ORDER" in source
    assert "QUARANTINED_STALE" in source
    assert "POSITION_ORIGIN_UNRESOLVED" in source
    assert "dispatch._adopt_observed_basis_if_needed_v1 = guarded_adopt" in source
    assert 'f"{client.base_url}/trade/v2/orders/{order_id}"' in source
