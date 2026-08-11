from __future__ import annotations

from cross_market_state import CrossMarketStateStore, build_cross_market_state
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore
from response_divergence import (
    ResponseDivergenceStore,
    evaluate_response_divergence,
    refresh_response_divergences,
)
from state_contracts import ComponentStatus, InformationStateSnapshot
from state_runtime_store import StateRuntimeStore


T0 = "2026-08-12T12:00:00+00:00"
T15 = "2026-08-12T12:15:00+00:00"


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


def _seed_cross_market(path, *, silver_end: float = 99.0):
    prices = {
        "Silver": (100.0, silver_end),
        "Gold": (200.0, 201.0),
        "Brent": (85.0, 87.0),
        "DXY": (100.0, 100.4),
    }
    for market, (start, end) in prices.items():
        _bar(path, market=market, stamp=T0, price=start)
        _bar(path, market=market, stamp=T15, price=end)
    snapshot = build_cross_market_state(path=path, market="Silver", as_of=T15)
    CrossMarketStateStore(path).save(snapshot)
    return snapshot


def _information(*, as_of: str = T0, safe_haven_change: float = 0.5) -> InformationStateSnapshot:
    return InformationStateSnapshot(
        snapshot_id=f"information:{as_of}:{safe_haven_change}",
        as_of=as_of,
        event_cluster_count=1,
        active_event_count=1,
        conflict_regime="ACTIVE_WAR",
        ceasefire_active=False,
        narrative_saturation=0.2,
        confirmation_quality=0.8,
        supply_risk=0.5,
        source_channels=("test",),
        component=ComponentStatus(
            observed_at=as_of,
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="selected-markets",
            engine_version="test",
        ),
        state_values={
            "conflict_pressure": 0.4,
            "energy_supply_risk": 0.4,
            "shipping_risk": 0.4,
            "safe_haven_pressure": 0.5,
            "usd_pressure": 0.0,
        },
        state_change={
            "conflict_pressure": 0.0,
            "energy_supply_risk": 0.0,
            "shipping_risk": 0.0,
            "safe_haven_pressure": safe_haven_change,
            "usd_pressure": 0.0,
        },
    )


def test_response_divergence_detects_opposite_silver_response(tmp_path):
    path = tmp_path / "divergence.db"
    cross = _seed_cross_market(path, silver_end=99.0)
    information = _information()

    result = evaluate_response_divergence(
        information,
        cross,
        market="Silver",
        window="15m",
    )

    assert result is not None
    assert result.expected_direction == "UP"
    assert result.realized_direction == "DOWN"
    assert result.status == "DIVERGENT"
    assert result.information_snapshot_id == information.snapshot_id
    assert result.cross_market_snapshot_id == cross.snapshot_id
    assert result.alignment_offset_seconds == 0.0
    assert result.supporting_observations["Brent"]["window_coverage"] == "VALID"
    assert result.supporting_observations["DXY"]["change"] is not None


def test_response_divergence_reports_aligned_response_without_causal_interpretation(tmp_path):
    path = tmp_path / "aligned.db"
    cross = _seed_cross_market(path, silver_end=101.0)

    result = evaluate_response_divergence(
        _information(),
        cross,
        market="Silver",
        window="15m",
    )

    assert result is not None
    assert result.status == "ALIGNED"
    assert result.realized_direction == "UP"
    assert "cause" not in result.to_record()
    assert "transmission" not in result.to_record()


def test_response_divergence_rejects_pre_event_or_misaligned_window(tmp_path):
    path = tmp_path / "misaligned.db"
    cross = _seed_cross_market(path)
    information = _information(as_of="2026-08-12T11:50:00+00:00")

    result = evaluate_response_divergence(
        information,
        cross,
        market="Silver",
        window="15m",
    )

    assert result is None


def test_response_divergence_ignores_neutral_information_impulse(tmp_path):
    path = tmp_path / "neutral.db"
    cross = _seed_cross_market(path)

    result = evaluate_response_divergence(
        _information(safe_haven_change=0.05),
        cross,
        market="Silver",
        window="15m",
    )

    assert result is None


def test_refresh_consumes_persisted_information_and_cross_market_snapshots(tmp_path):
    path = tmp_path / "refresh.db"
    information = _information()
    StateRuntimeStore(path).save_information_state(information)
    cross = _seed_cross_market(path, silver_end=98.5)

    results = refresh_response_divergences(path, market="Silver")

    assert len(results) == 1
    assert results[0].window == "15m"
    assert results[0].status == "DIVERGENT"
    persisted = ResponseDivergenceStore(path).load_latest(market="Silver")
    assert persisted is not None
    assert persisted.divergence_id == results[0].divergence_id
    assert persisted.cross_market_snapshot_id == cross.snapshot_id


def test_response_divergence_persistence_is_immutable(tmp_path):
    path = tmp_path / "store.db"
    cross = _seed_cross_market(path)
    result = evaluate_response_divergence(
        _information(),
        cross,
        market="Silver",
        window="15m",
    )
    assert result is not None

    store = ResponseDivergenceStore(path)
    store.save(result)
    store.save(result)

    loaded = store.load_latest(market="Silver")
    assert loaded is not None
    assert loaded.to_record() == result.to_record()
