from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import realtime_stream_entrypoint as entrypoint
from saxo_infoprice_probe import InfoPriceDiagnostic


def _diagnostic(*, market_open, last_updated):
    return InfoPriceDiagnostic(
        market="US Tech 100 NAS · Saxo 4912",
        uic=4912,
        asset_type="CfdOnIndex",
        last_updated=last_updated,
        is_market_open=market_open,
        delayed_by_minutes=0.0,
        error_code=None,
        price_type_bid="OldIndicative",
        price_type_ask="OldIndicative",
        bid=29491.4,
        ask=29493.4,
        mid=29492.4,
        last_traded=29492.52,
    )


def test_db_path_from_worker_argv():
    assert entrypoint._db_path_from_argv(["--db", "custom.db", "--refresh-ms", "1000"]) == "custom.db"
    assert entrypoint._db_path_from_argv(["--db=other.db"]) == "other.db"


def test_authoritative_cutoff_requires_infoprice_closed_state():
    closed = entrypoint._authoritative_closed_cutoff(
        _diagnostic(market_open=False, last_updated="2026-09-04T20:59:59.003Z")
    )
    assert closed == datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)
    assert entrypoint._authoritative_closed_cutoff(
        _diagnostic(market_open=True, last_updated="2026-09-07T07:00:01Z")
    ) is None
    assert entrypoint._authoritative_closed_cutoff(
        _diagnostic(market_open=False, last_updated=None)
    ) is None


def test_preflight_repairs_each_closed_product_independently(monkeypatch, tmp_path):
    instrument = SimpleNamespace(uic=4912)
    monkeypatch.setattr(entrypoint, "configured_client", lambda: object())
    monkeypatch.setattr(entrypoint, "_runtime_instruments", lambda: {"US Tech 100 NAS · Saxo 4912": instrument})
    monkeypatch.setattr(entrypoint, "RealtimeMarketDataStore", lambda path: SimpleNamespace(path=path))
    monkeypatch.setattr(
        entrypoint,
        "fetch_infoprice_diagnostics",
        lambda **kwargs: (_diagnostic(market_open=False, last_updated="2026-09-04T20:59:59.003Z"),),
    )
    calls = []

    def fake_repair(**kwargs):
        calls.append(kwargs)
        return 7

    monkeypatch.setattr(entrypoint, "repair_closed_market_realtime_tail", fake_repair)

    removed = entrypoint.run_closed_market_preflight(db_path=str(tmp_path / "pg.db"))

    assert removed == 7
    assert len(calls) == 1
    assert calls[0]["market"] == "US Tech 100 NAS · Saxo 4912"
    assert calls[0]["cutoff"] == datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)
