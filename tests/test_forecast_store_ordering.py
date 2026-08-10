from forecast_contracts import ForecastSnapshot
from forecast_store import ForecastStore


def _snapshot(suffix: str) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id=f"forecast:{suffix}",
        market="Brent",
        as_of="2026-08-10T00:00:00+00:00",
        reference_price=84.0,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.6,
        expected_move_low_pct=0.2,
        expected_move_high_pct=0.8,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id=f"decision:{suffix}",
        information_snapshot_id=f"information:{suffix}",
        market_snapshot_id=f"market:{suffix}",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_same_as_of_forecasts_reload_in_stable_order(tmp_path) -> None:
    store = ForecastStore(tmp_path / "pg.db")
    snapshots = [_snapshot("a"), _snapshot("b"), _snapshot("c")]
    store.save_all(snapshots)

    first = [item.forecast_id for item in store.load_all(market="Brent", limit=3)]
    second = [item.forecast_id for item in ForecastStore(tmp_path / "pg.db").load_all(market="Brent", limit=3)]

    assert first == second
    assert set(first) == {item.forecast_id for item in snapshots}
