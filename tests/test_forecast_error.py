from forecast_error import (
    FORECAST_ERROR_VERSION,
    ForecastErrorStore,
    build_forecast_error,
    refresh_forecast_errors,
)
from forecast_learning import ForecastOutcome


def _outcome(**overrides) -> ForecastOutcome:
    values = dict(
        forecast_id="forecast:test",
        market="Gold",
        forecast_as_of="2026-08-12T10:00:00+00:00",
        evaluated_at="2026-08-12T14:00:00+00:00",
        status="COMPLETE",
        progress=1.0,
        horizon_hours=4.0,
        reference_price=4400.0,
        last_observed_at="2026-08-12T14:00:00+00:00",
        last_price=4444.0,
        realized_move_pct=1.0,
        expected_move_low_pct=0.6,
        expected_move_high_pct=1.4,
        interval_hit=True,
        direction_hit=True,
        max_up_pct=1.2,
        max_down_pct=-0.2,
        mfe_pct=1.2,
        mae_pct=-0.2,
        sample_count=240,
    )
    values.update(overrides)
    return ForecastOutcome(**values)


def test_center_error_uses_forecast_interval_as_normalized_coordinate():
    observation = build_forecast_error(_outcome(realized_move_pct=1.0))

    assert observation is not None
    assert observation.expected_center_pct == 1.0
    assert observation.expected_half_width_pct == 0.4
    assert observation.signed_center_error_pct == 0.0
    assert observation.normalized_center_error == 0.0
    assert observation.normalized_interval_error == 0.0
    assert observation.classification == "IN_INTERVAL"


def test_error_sign_preserves_whether_model_was_too_bullish_or_too_bearish():
    below = build_forecast_error(
        _outcome(realized_move_pct=0.2, interval_hit=False, direction_hit=True)
    )
    above = build_forecast_error(
        _outcome(realized_move_pct=1.8, interval_hit=False, direction_hit=True)
    )

    assert below is not None and above is not None
    assert below.signed_center_error_pct < 0
    assert below.normalized_center_error == -2.0
    assert below.normalized_interval_error == -1.0
    assert above.signed_center_error_pct > 0
    assert above.normalized_center_error == 2.0
    assert above.normalized_interval_error == 1.0


def test_direction_miss_is_explicit_and_not_reinterpreted():
    observation = build_forecast_error(
        _outcome(realized_move_pct=-0.5, interval_hit=False, direction_hit=False)
    )

    assert observation is not None
    assert observation.classification == "DIRECTION_MISS"
    assert observation.normalized_center_error < -1.0


def test_incomplete_outcome_is_not_frozen_as_error():
    assert build_forecast_error(_outcome(status="PARTIAL", progress=0.5)) is None


def test_zero_width_interval_keeps_raw_error_without_inventing_normalization():
    observation = build_forecast_error(
        _outcome(
            realized_move_pct=1.2,
            expected_move_low_pct=1.0,
            expected_move_high_pct=1.0,
            interval_hit=False,
        )
    )

    assert observation is not None
    assert observation.signed_center_error_pct == 0.2
    assert observation.normalized_center_error is None
    assert observation.normalized_interval_error is None


def test_persistence_is_immutable_per_forecast_and_scoring_version(tmp_path):
    path = tmp_path / "error.db"
    first = build_forecast_error(_outcome(realized_move_pct=1.0))
    revised = build_forecast_error(_outcome(realized_move_pct=1.2))
    assert first is not None and revised is not None
    assert first.error_id == revised.error_id

    store = ForecastErrorStore(path)
    assert store.save(first) is True
    assert store.save(revised) is False

    loaded = store.load_all(market="Gold", horizon_hours=4.0)
    assert loaded == [first]
    assert loaded[0].scoring_version == FORECAST_ERROR_VERSION


def test_refresh_filters_to_complete_scored_outcomes_and_is_idempotent(tmp_path):
    path = tmp_path / "refresh.db"
    outcomes = [
        _outcome(forecast_id="forecast:one", realized_move_pct=1.0),
        _outcome(forecast_id="forecast:two", status="PARTIAL", progress=0.5),
    ]

    inserted = refresh_forecast_errors(path, outcomes=outcomes)
    repeated = refresh_forecast_errors(path, outcomes=outcomes)

    assert len(inserted) == 1
    assert repeated == []
    assert ForecastErrorStore(path).load_all(market="Gold", horizon_hours=4.0) == inserted
