from __future__ import annotations

from types import SimpleNamespace

import runtime_subscription_bridge_v2 as bridge_v2
import saxo_discovered_history_seed_v2 as seed_v2
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument


def _source(*, discovered: bool = True) -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=7,
        market_name="US Tech 100 NAS · Saxo 4912",
        instrument_id=9,
        instrument_type="CfdOnIndex",
        display_name="US Tech 100 NAS [CfdOnIndex:4912]",
        provider="saxo",
        provider_instrument_id="4912",
        asset_type="CfdOnIndex",
        symbol="USNAS100.I",
        price_multiplier=1.0,
        metadata={
            "description": "US Tech 100 NAS",
            **({"discovery_origin": "SAXO_OPEN_POSITION"} if discovered else {}),
        },
    )


def test_only_open_position_discovered_sources_are_seed_candidates(monkeypatch):
    monkeypatch.setattr(seed_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(seed_v2, "list_subscribed_sources_v2", lambda **_kwargs: (_source(discovered=False),))

    summary = seed_v2.seed_discovered_saxo_history_once_v2(client=object())

    assert summary.candidates == 0
    assert summary.attempted == 0


def test_ready_discovered_source_is_noop(monkeypatch):
    seed_v2._LAST_ATTEMPT_MONO.clear()
    monkeypatch.setattr(seed_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(seed_v2, "list_subscribed_sources_v2", lambda **_kwargs: (_source(),))
    monkeypatch.setattr(seed_v2, "CanonicalMarketBarStoreV2", lambda _path: object())
    monkeypatch.setattr(seed_v2, "_recent_bar_count", lambda *_args, **_kwargs: seed_v2.SEED_MIN_1M_BARS)
    monkeypatch.setattr(
        seed_v2,
        "RealtimeMarketDataStore",
        lambda _path: (_ for _ in ()).throw(AssertionError("ready market must not open seed store")),
    )

    summary = seed_v2.seed_discovered_saxo_history_once_v2(client=object())

    assert summary.candidates == 1
    assert summary.already_ready == 1
    assert summary.attempted == 0


def test_insufficient_discovered_source_gets_deep_seed(monkeypatch):
    seed_v2._LAST_ATTEMPT_MONO.clear()
    source = _source()
    counts = iter((400, seed_v2.SEED_MIN_1M_BARS + 50))
    captured = {}

    monkeypatch.setattr(seed_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(seed_v2, "list_subscribed_sources_v2", lambda **_kwargs: (source,))
    monkeypatch.setattr(seed_v2, "CanonicalMarketBarStoreV2", lambda _path: object())
    monkeypatch.setattr(seed_v2, "RealtimeMarketDataStore", lambda _path: "STORE")
    monkeypatch.setattr(seed_v2, "_recent_bar_count", lambda *_args, **_kwargs: next(counts))

    def _repair(**kwargs):
        captured.update(kwargs)
        return 1500

    monkeypatch.setattr(seed_v2, "repair_recent_market_history", _repair)

    summary = seed_v2.seed_discovered_saxo_history_once_v2(
        client="CLIENT",
        monotonic_now=100.0,
    )

    assert summary.attempted == 1
    assert summary.bars_saved == 1500
    assert summary.ready_after_seed == 1
    assert summary.failed == 0
    assert captured["client"] == "CLIENT"
    assert captured["store"] == "STORE"
    assert captured["market"] == source.market_name
    assert captured["instrument"].uic == 4912
    assert captured["instrument"].asset_type == "CfdOnIndex"
    assert captured["lookback_hours"] == seed_v2.SEED_LOOKBACK_HOURS
    assert captured["page_size"] == seed_v2.SEED_PAGE_SIZE
    assert captured["max_pages"] == seed_v2.SEED_MAX_PAGES


def test_incomplete_seed_retry_is_throttled(monkeypatch):
    seed_v2._LAST_ATTEMPT_MONO.clear()
    source = _source()
    repairs = []

    monkeypatch.setattr(seed_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(seed_v2, "list_subscribed_sources_v2", lambda **_kwargs: (source,))
    monkeypatch.setattr(seed_v2, "CanonicalMarketBarStoreV2", lambda _path: object())
    monkeypatch.setattr(seed_v2, "RealtimeMarketDataStore", lambda _path: object())
    monkeypatch.setattr(seed_v2, "_recent_bar_count", lambda *_args, **_kwargs: 100)
    monkeypatch.setattr(seed_v2, "repair_recent_market_history", lambda **_kwargs: repairs.append(1) or 100)

    first = seed_v2.seed_discovered_saxo_history_once_v2(client=object(), monotonic_now=100.0)
    second = seed_v2.seed_discovered_saxo_history_once_v2(client=object(), monotonic_now=101.0)

    assert first.attempted == 1
    assert second.attempted == 0
    assert repairs == [1]


def test_scheduler_starts_daemon_without_running_seed_inline(monkeypatch):
    captured = {}

    class _FakeThread:
        def __init__(self, *, target, kwargs, name, daemon):
            captured.update(target=target, kwargs=kwargs, name=name, daemon=daemon)
            self.started = False

        def is_alive(self):
            return self.started

        def start(self):
            self.started = True
            captured["started"] = True

    monkeypatch.setattr(seed_v2.threading, "Thread", _FakeThread)
    seed_v2._SEED_THREAD = None
    seed_v2._LAST_SEED_SCHEDULE_MONO = 0.0
    try:
        assert seed_v2.start_discovered_saxo_history_seed_v2(
            db_path="test.db",
            monotonic_now=100.0,
        ) is True
        assert captured["started"] is True
        assert captured["target"] is seed_v2._run_scheduled_seed
        assert captured["kwargs"] == {"db_path": "test.db"}
        assert captured["name"] == "pricegauger-discovered-history-seed"
        assert captured["daemon"] is True
        assert seed_v2.start_discovered_saxo_history_seed_v2(
            db_path="test.db",
            monotonic_now=101.0,
        ) is False
    finally:
        seed_v2._SEED_THREAD = None
        seed_v2._LAST_SEED_SCHEDULE_MONO = 0.0


def test_registry_refresh_survives_deep_seed_scheduling_failure(monkeypatch):
    configured = {
        "Gold": SaxoInstrument(asset="Gold", uic=123, asset_type="ContractFutures"),
    }
    monkeypatch.setattr(bridge_v2, "discover_open_saxo_positions_once_v2", lambda: SimpleNamespace(
        onboarded=0,
        subscriptions_reactivated=0,
        failed=0,
        observed_products=0,
        already_subscribed=0,
    ))
    monkeypatch.setattr(
        bridge_v2,
        "start_discovered_saxo_history_seed_v2",
        lambda: (_ for _ in ()).throw(RuntimeError("scheduler unavailable")),
    )
    monkeypatch.setattr(bridge_v2, "list_subscribed_sources_v2", lambda **_kwargs: ())

    result = bridge_v2.load_runtime_instruments_v2(configured)

    assert result.instruments == configured
    assert result.registry_markets == ()
