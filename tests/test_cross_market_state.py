from __future__ import annotations

from cross_market_state import (
    CrossMarketObservation,
    CrossMarketStateStore,
    build_cross_market_state,
)
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore


def _bar(path, *, market: str, stamp: str, price: float) -> None:
    RealtimeMarketDataStore(path).save_bar(
        RealtimeBar1m(
            market=market,
            bar_time=stamp,
            open=price,
            high=price,
            low=price,
            close=price,
            sample_count=1,
            provider="Saxo OpenAPI",
            uic=123,
            asset_type="ContractFutures",
            symbol="TEST",
        )
    )


def _seed_market(path, market: str, prices: tuple[float, float, float, float]) -> None:
    for stamp, price in zip(
        (
            "2026-08-11T08:00:00+00:00",
            "2026-08-11T11:00:00+00:00",
            "2026-08-11T11:45:00+00:00",
            "2026-08-11T12:00:00+00:00",
        ),
        prices,
    ):
        _bar(path, market=market, stamp=stamp, price=price)


def test_build_cross_market_state_reads_canonical_returns_and_marks_yields_missing(tmp_path):
    path = tmp_path / "cross.db"
    _seed_market(path, "Silver", (100.0, 102.0, 103.0, 104.0))
    _seed_market(path, "Gold", (200.0, 202.0, 204.0, 206.0))
    _seed_market(path, "Brent", (80.0, 82.0, 84.0, 88.0))
    _seed_market(path, "DXY", (100.0, 100.5, 100.8, 101.0))

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
    )

    by_name = {item.name: item for item in snapshot.observations}
    assert by_name["Silver"].freshness == "FRESH"
    assert round(by_name["Silver"].change_4h or 0.0, 6) == 4.0
    assert round(by_name["Brent"].change_1h or 0.0, 6) == round((88.0 / 82.0 - 1.0) * 100.0, 6)
    assert by_name["US2Y"].freshness == "MISSING"
    assert by_name["US10Y"].value is None
    assert snapshot.curve_spreads_bp["2s10s"] is None


def test_cross_market_state_calculates_yield_curve_spreads_and_changes(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _seed_market(path, market, (100.0, 100.0, 100.0, 100.0))

    yields = (
        CrossMarketObservation("US2Y", "YIELD_PCT", "2026-08-11T12:00:00+00:00", 4.10, 2.0, 5.0, 8.0, "FRESH", "test-yield", "US2Y"),
        CrossMarketObservation("US10Y", "YIELD_PCT", "2026-08-11T12:00:00+00:00", 4.70, 4.0, 8.0, 10.0, "FRESH", "test-yield", "US10Y"),
        CrossMarketObservation("US30Y", "YIELD_PCT", "2026-08-11T12:00:00+00:00", 4.95, 5.0, 10.0, 14.0, "FRESH", "test-yield", "US30Y"),
    )

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
        yield_observations=yields,
    )

    assert round(snapshot.curve_spreads_bp["2s10s"] or 0.0, 6) == 60.0
    assert round(snapshot.curve_spreads_bp["10s30s"] or 0.0, 6) == 25.0
    assert snapshot.curve_changes_bp["2s10s"]["1h"] == 3.0
    assert snapshot.curve_changes_bp["10s30s"]["4h"] == 4.0


def test_cross_market_state_store_is_immutable_and_loads_latest(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _seed_market(path, market, (100.0, 100.0, 100.0, 100.0))

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
    )
    store = CrossMarketStateStore(path)
    store.save(snapshot)
    store.save(snapshot)

    loaded = store.load_latest(market="Silver")
    assert loaded is not None
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.to_record() == snapshot.to_record()
