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


def _yield_observation(name: str, value: float, changes: tuple[float, float, float]) -> CrossMarketObservation:
    references = {
        "15m": "2026-08-11T11:45:00+00:00",
        "1h": "2026-08-11T11:00:00+00:00",
        "4h": "2026-08-11T08:00:00+00:00",
    }
    return CrossMarketObservation(
        name=name,
        kind="YIELD_PCT",
        observed_at="2026-08-11T12:00:00+00:00",
        value=value,
        change_15m=changes[0],
        change_1h=changes[1],
        change_4h=changes[2],
        latest_observation_freshness="FRESH",
        provider="test-yield",
        instrument=name,
        latest_observation_age_seconds=0.0,
        window_coverage={"15m": "VALID", "1h": "VALID", "4h": "VALID"},
        window_reference_at=references,
        window_reference_offset_seconds={"15m": 0.0, "1h": 0.0, "4h": 0.0},
    )


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
    silver = by_name["Silver"]
    assert silver.latest_observation_freshness == "FRESH"
    assert silver.latest_observation_age_seconds == 0.0
    assert silver.window_coverage == {"15m": "VALID", "1h": "VALID", "4h": "VALID"}
    assert silver.window_reference_at["15m"] == "2026-08-11T11:45:00+00:00"
    assert silver.window_reference_offset_seconds["15m"] == 0.0
    assert round(silver.change_4h or 0.0, 6) == 4.0
    assert round(by_name["Brent"].change_1h or 0.0, 6) == round((88.0 / 82.0 - 1.0) * 100.0, 6)
    assert by_name["US2Y"].latest_observation_freshness == "MISSING"
    assert by_name["US10Y"].value is None
    assert snapshot.curve_spreads_bp["2s10s"] is None


def test_short_window_is_missing_when_reference_is_too_far_from_target(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _bar(path, market=market, stamp="2026-08-11T08:00:00+00:00", price=100.0)
        _bar(path, market=market, stamp="2026-08-11T11:00:00+00:00", price=101.0)
        _bar(path, market=market, stamp="2026-08-11T11:30:00+00:00", price=102.0)
        _bar(path, market=market, stamp="2026-08-11T12:00:00+00:00", price=103.0)

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
    )

    silver = {item.name: item for item in snapshot.observations}["Silver"]
    assert silver.latest_observation_freshness == "FRESH"
    assert silver.change_15m is None
    assert silver.window_coverage["15m"] == "MISSING"
    assert silver.window_reference_at["15m"] == "2026-08-11T11:30:00+00:00"
    assert silver.window_reference_offset_seconds["15m"] == 15 * 60
    assert silver.window_coverage["1h"] == "VALID"
    assert silver.window_coverage["4h"] == "VALID"


def test_stale_latest_observation_invalidates_all_return_windows(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _bar(path, market=market, stamp="2026-08-11T08:00:00+00:00", price=100.0)
        _bar(path, market=market, stamp="2026-08-11T10:50:00+00:00", price=101.0)
        _bar(path, market=market, stamp="2026-08-11T11:35:00+00:00", price=102.0)
        _bar(path, market=market, stamp="2026-08-11T11:50:00+00:00", price=103.0)

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
    )

    silver = {item.name: item for item in snapshot.observations}["Silver"]
    assert silver.latest_observation_freshness == "STALE"
    assert silver.latest_observation_age_seconds == 10 * 60
    assert silver.change_15m is None
    assert silver.change_1h is None
    assert silver.change_4h is None
    assert silver.window_coverage == {"15m": "MISSING", "1h": "MISSING", "4h": "MISSING"}


def test_cross_market_state_calculates_yield_curve_spreads_and_changes(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _seed_market(path, market, (100.0, 100.0, 100.0, 100.0))

    yields = (
        _yield_observation("US2Y", 4.10, (2.0, 5.0, 8.0)),
        _yield_observation("US10Y", 4.70, (4.0, 8.0, 10.0)),
        _yield_observation("US30Y", 4.95, (5.0, 10.0, 14.0)),
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


def test_curve_change_is_missing_when_a_yield_window_is_not_valid(tmp_path):
    path = tmp_path / "cross.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _seed_market(path, market, (100.0, 100.0, 100.0, 100.0))

    two_year = _yield_observation("US2Y", 4.10, (2.0, 5.0, 8.0))
    ten_year = _yield_observation("US10Y", 4.70, (4.0, 8.0, 10.0))
    thirty_year = _yield_observation("US30Y", 4.95, (5.0, 10.0, 14.0))
    invalid_ten = CrossMarketObservation(
        name=ten_year.name,
        kind=ten_year.kind,
        observed_at=ten_year.observed_at,
        value=ten_year.value,
        change_15m=None,
        change_1h=ten_year.change_1h,
        change_4h=ten_year.change_4h,
        latest_observation_freshness=ten_year.latest_observation_freshness,
        provider=ten_year.provider,
        instrument=ten_year.instrument,
        latest_observation_age_seconds=ten_year.latest_observation_age_seconds,
        window_coverage={"15m": "MISSING", "1h": "VALID", "4h": "VALID"},
        window_reference_at=ten_year.window_reference_at,
        window_reference_offset_seconds=ten_year.window_reference_offset_seconds,
    )

    snapshot = build_cross_market_state(
        path=path,
        market="Silver",
        as_of="2026-08-11T12:00:00+00:00",
        yield_observations=(two_year, invalid_ten, thirty_year),
    )

    assert snapshot.curve_changes_bp["2s10s"]["15m"] is None
    assert snapshot.curve_changes_bp["2s10s"]["1h"] == 3.0


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
