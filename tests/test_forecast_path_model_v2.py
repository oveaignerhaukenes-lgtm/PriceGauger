from types import SimpleNamespace

from forecast_path_model_v2 import build_forecast_path_v2


def _state(snapshot, *, trend="BULLISH", momentum="BULLISH", structure="HH_HL"):
    return SimpleNamespace(
        trend_state=trend,
        momentum_state=momentum,
        structure_state=structure,
        snapshots={"5m": dict(snapshot), "30m": dict(snapshot), "1h": dict(snapshot)},
    )


def _snapshot(**overrides):
    values = {
        "atr_14_pct": 0.18,
        "distance_to_support_pct": 0.42,
        "distance_to_resistance_pct": 0.48,
        "rsi_14": 58.0,
        "rsi_change_3": 1.5,
        "macd_histogram": 0.10,
        "macd_histogram_change_3": 0.02,
        "recent_return_3_pct": 0.12,
    }
    values.update(overrides)
    return values


def test_four_hour_range_uses_thirty_minute_levels_and_draws_both_sides():
    path = build_forecast_path_v2(
        state=_state(_snapshot(macd_histogram=-0.08, macd_histogram_change_3=-0.01), momentum="BEARISH", structure="MIXED"),
        horizon_seconds=4 * 3600,
        direction="BULLISH",
        expected_return=0.00095,
        lower_return=-0.00512,
        upper_return=0.00703,
        path_shape="MEAN_REVERTING_OR_RANGE",
    )

    assert path.source_timeframe == "30m"
    assert path.points[1][1] < 0
    assert path.points[3][1] > 0
    assert path.points[-1] == (1.0, 0.00095)
    assert path.expected_low_return < 0 < path.expected_high_return
    assert "TEST NED" in path.phases


def test_overbought_cooling_momentum_becomes_push_exhaustion_retrace():
    path = build_forecast_path_v2(
        state=_state(
            _snapshot(
                rsi_14=74.0,
                rsi_change_3=-4.0,
                macd_histogram=0.12,
                macd_histogram_change_3=-0.05,
            )
        ),
        horizon_seconds=4 * 3600,
        direction="BULLISH",
        expected_return=0.0015,
        lower_return=-0.006,
        upper_return=0.007,
        path_shape="TREND_CONTINUATION",
    )

    assert path.points[1][1] > 0
    assert path.points[2][1] > path.points[1][1]
    assert path.points[3][1] < 0
    assert path.points[-1] == (1.0, 0.0015)
    assert path.phases[:3] == ("SISTE PUSH OPP", "EXHAUSTION", "RETRACE")
    assert "MACD kjølner" in path.rationale


def test_oversold_cooling_bearish_momentum_mirrors_into_rebound():
    path = build_forecast_path_v2(
        state=_state(
            _snapshot(
                rsi_14=27.0,
                rsi_change_3=3.0,
                macd_histogram=-0.10,
                macd_histogram_change_3=0.04,
            ),
            trend="BEARISH",
            momentum="BEARISH",
            structure="LH_LL",
        ),
        horizon_seconds=3600,
        direction="BEARISH",
        expected_return=-0.002,
        lower_return=-0.008,
        upper_return=0.005,
        path_shape="TREND_CONTINUATION",
    )

    assert path.points[1][1] < 0
    assert path.points[2][1] < path.points[1][1]
    assert path.points[3][1] > 0
    assert "REBOUND" in path.phases
