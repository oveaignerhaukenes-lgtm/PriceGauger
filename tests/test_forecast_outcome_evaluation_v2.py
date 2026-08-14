from __future__ import annotations

from uuid import UUID

from forecast_outcome_evaluation_v2 import (
    ForecastClaimV2,
    direction_hit_v2,
    evaluate_forecast_claim_v2,
    interval_hit_v2,
)


FORECAST_ID = UUID("11111111-1111-1111-1111-111111111111")


def _claim(**changes) -> ForecastClaimV2:
    values = {
        "forecast_id": FORECAST_ID,
        "market_id": 7,
        "as_of": "2026-08-14T10:00:00+00:00",
        "horizon_seconds": 300,
        "baseline_return": 0.01,
        "composed_return": 0.02,
        "lower_return": 0.005,
        "upper_return": 0.03,
    }
    values.update(changes)
    return ForecastClaimV2(**values)


def test_complete_outcome_uses_active_horizon_and_composed_error():
    outcome = evaluate_forecast_claim_v2(
        _claim(),
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 101.0),
            ("2026-08-14T10:02:00Z", 101.5),
            ("2026-08-14T10:03:00Z", 102.0),
            ("2026-08-14T10:04:00Z", 102.5),
            ("2026-08-14T10:05:00Z", 103.0),
        ],
    )

    assert outcome is not None
    assert outcome.status == "COMPLETE"
    assert outcome.reference_price == 100.0
    assert outcome.realized_terminal_price == 103.0
    assert outcome.realized_return == 0.03
    assert outcome.signed_error == 0.01
    assert outcome.absolute_error == 0.01
    assert outcome.matured_at == "2026-08-14T10:05:00+00:00"
    assert direction_hit_v2(_claim(), outcome) is True
    assert interval_hit_v2(_claim(), outcome) is True


def test_closed_market_gap_does_not_consume_horizon():
    claim = _claim(horizon_seconds=120)
    outcome = evaluate_forecast_claim_v2(
        claim,
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 101.0),
            # Long closure: this interval must not mature the forecast.
            ("2026-08-17T10:00:00Z", 102.0),
            ("2026-08-17T10:01:00Z", 103.0),
        ],
    )

    assert outcome is not None
    assert outcome.matured_at == "2026-08-17T10:01:00+00:00"
    assert outcome.realized_terminal_price == 103.0


def test_unmatured_forecast_returns_none_instead_of_partial_outcome():
    outcome = evaluate_forecast_claim_v2(
        _claim(horizon_seconds=600),
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:03:00Z", 101.0),
        ],
    )

    assert outcome is None


def test_points_are_sorted_deduplicated_and_pre_forecast_data_is_ignored():
    outcome = evaluate_forecast_claim_v2(
        _claim(horizon_seconds=60, composed_return=-0.01, lower_return=-0.03, upper_return=0.0),
        [
            ("2026-08-14T09:59:00Z", 500.0),
            ("2026-08-14T10:01:00Z", 98.0),
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 99.0),
        ],
    )

    assert outcome is not None
    assert outcome.reference_price == 100.0
    assert outcome.realized_terminal_price == 99.0
    assert direction_hit_v2(_claim(composed_return=-0.01), outcome) is True


def test_missing_prediction_still_records_objective_realized_result():
    claim = _claim(composed_return=None, lower_return=None, upper_return=None, horizon_seconds=60)
    outcome = evaluate_forecast_claim_v2(
        claim,
        [
            ("2026-08-14T10:00:00Z", 100.0),
            ("2026-08-14T10:01:00Z", 101.0),
        ],
    )

    assert outcome is not None
    assert outcome.realized_return == 0.01
    assert outcome.signed_error is None
    assert outcome.absolute_error is None
    assert direction_hit_v2(claim, outcome) is None
    assert interval_hit_v2(claim, outcome) is None
