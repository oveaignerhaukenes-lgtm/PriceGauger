"""Collection-only rollover backoff + read-only unresolved UIC diagnostics."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import futures_rollover_discovery_v2 as discovery
import futures_rollover_v1 as rollover
import runtime_subscription_bridge_v2 as bridge
from saxo_provider import SaxoInstrument
from instrument_registry_v2 import InstrumentSourceV2


def _source():
    return InstrumentSourceV2(
        market_id=9, market_name="Natural Gas", instrument_id=91,
        instrument_type="future", display_name="Natural Gas Sep 2026",
        provider="saxo", provider_instrument_id="50419383",
        asset_type="ContractFutures", symbol="NGU6", price_multiplier=1.0,
        metadata={"expiry": "2026-08-27T18:30:00Z"},
    )


def test_collection_refresh_not_run_on_each_stream_heartbeat(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(bridge, "_ROLLOVER_NEXT_AT", 0.0)
    monkeypatch.setattr(bridge, "_rollover_monotonic_v2", lambda: clock[0])
    calls = []
    monkeypatch.setattr(
        bridge, "resolve_saxo_futures_rollovers_once_v1",
        lambda: calls.append(clock[0]) or SimpleNamespace(
            checked=5, eligible=1, rolled=0, unchanged=4, failed=1
        ),
    )
    bridge._resolve_futures_rollovers_best_effort()
    assert calls == [100.0]
    for stamp in (103., 107., 200., 219.99):
        clock[0] = stamp
        bridge._resolve_futures_rollovers_best_effort()
    assert calls == [100.0]
    clock[0] = 220.0
    bridge._resolve_futures_rollovers_best_effort()
    assert calls == [100.0, 220.0]


def test_broker_candidates_logged_read_only_but_never_guessed(monkeypatch, caplog):
    class ArchivedNotFound:
        def instrument_details(self, instrument):
            return {
                "Uic": int(instrument.uic),
                "ExpiryDateTime": "2026-08-27T18:30:00Z",
                "IsTradable": False,
                "Symbol": "NGU6",
            }
        def _get(self, path, params=None):
            assert path == "ref/v1/instruments"
            if "Uics" in params:
                return {"Data": []}
            assert params["IncludeNonTradable"] is True
            return {"Data": [
                {"Identifier": 77777701,
                 "Symbol": "NGX6",
                 "Description": "Natural Gas November 2026",
                 "AssetType": "ContractFutures",
                 "ExchangeId": "NYMEX",
                 "PrimaryListing": 77777701,
                 "DisplayHint": "None"},
                {"Identifier": 444444,
                 "Symbol": "FAKE",
                 "AssetType": "CfdOnIndex"}
            ]}
    monkeypatch.setattr(rollover,"list_subscribed_sources_v2",
                        lambda provider=None:(_source(),))
    def no_mutation(**kwargs):
        raise AssertionError("An unrelated Saxo candidate cannot be rolled")
    monkeypatch.setattr(rollover,"_apply_rollover",no_mutation)
    with caplog.at_level(logging.WARNING):
        summary=discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
            client=ArchivedNotFound()
        )
    assert summary.rolled==0
    assert summary.failed==1
    out=caplog.text
    assert "UNRESOLVED" in out
    assert "READ_ONLY" in out
    assert "77777701" in out
    assert "NGX6" in out
    assert "444444" not in out


def test_rollover_cooldown_does_not_change_live_source_or_orders():
    from pathlib import Path
    src=Path("runtime_subscription_bridge_v2.py").read_text()
    assert "_resolve_futures_rollovers_best_effort()" in src
    assert "place_order" not in src
    assert "autotrader_live_open" not in src
    assert "autotrader_live_close" not in src
