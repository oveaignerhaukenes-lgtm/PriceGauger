"""Regression: fast local subscription refresh must not trigger 15s Saxo/history scans."""
from types import SimpleNamespace

import pytest
import realtime_worker
import runtime_subscription_bridge_v2 as bridge
from saxo_provider import SaxoInstrument


def test_fast_registry_refresh_skips_all_auxiliary_network_scanners(monkeypatch):
    def unexpected():
        raise AssertionError("Auxiliary broker/history call in fast registry poll")
    for name in ("_discover_open_positions_best_effort",
                 "_prepare_futures_rollover_audit_best_effort",
                 "_resolve_futures_rollovers_best_effort",
                 "_seed_discovered_history_best_effort"):
        monkeypatch.setattr(bridge,name,unexpected)
    monkeypatch.setattr(bridge,"list_subscribed_sources_v2",lambda **kw: ())
    base={"Tech100":SaxoInstrument(asset="Tech100",uic=4912,asset_type="CfdOnIndex")}
    result=bridge.load_runtime_instruments_v2(base,refresh_auxiliary=False)
    assert result.instruments==base


def test_watch_registry_and_expensive_saxo_discovery_have_separate_cadence(monkeypatch):
    market=SaxoInstrument(asset="Tech100",uic=4912,asset_type="CfdOnIndex")
    configured={"Tech100":market}
    calls=[]
    timer={"s":0}

    def fake_sleep(seconds):
        timer["s"]+=seconds
        if timer["s"]>345:
            raise StopIteration

    def fake_load(_configured, *, refresh_auxiliary):
        assert _configured==configured
        calls.append((timer["s"],refresh_auxiliary))
        return SimpleNamespace(instruments=dict(configured))

    monkeypatch.setattr(realtime_worker.time,"sleep",fake_sleep)
    monkeypatch.setattr(realtime_worker.time,"monotonic",lambda:1000+timer["s"])
    monkeypatch.setattr(realtime_worker,"using_postgres",lambda:True)
    monkeypatch.setattr(realtime_worker,"load_runtime_instruments_v2",fake_load)
    monkeypatch.delenv("PRICEGAUGER_RUNTIME_DISCOVERY_SECONDS",raising=False)
    with pytest.raises(StopIteration):
        realtime_worker._watch_v2_registry(
            configured=configured,runtime_instruments=dict(configured),
            restart_requested=SimpleNamespace(set=lambda:None),poll_seconds=15)
    assert calls[0]==(15,False)
    assert [t for t,deep in calls if deep]==[300]
    assert len(calls)>=22
