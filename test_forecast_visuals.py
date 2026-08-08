from __future__ import annotations

from forecast_contracts import ForecastSnapshot
from forecast_visuals import build_trajectory, render_forecast_svg


def _forecast(**overrides):
    values = dict(
        forecast_id="forecast:test",
        market="Gold",
        as_of="2026-08-08T22:00:00+00:00",
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.7,
        confidence=0.65,
        expected_move_low_pct=0.5,
        expected_move_high_pct=1.5,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:1",
        information_snapshot_id="information:1",
        market_snapshot_id="market:1",
        status="READY",
        missing_inputs=(),
        status_reason="Aligned state",
    )
    values.update(overrides)
    return ForecastSnapshot(**values)


def test_trajectory_uses_equal_history_and_forecast_halves():
    forecast = _forecast()
    history = (
        ("2026-08-08T18:00:00+00:00", 4160.0),
        ("2026-08-08T20:00:00+00:00", 4180.0),
        ("2026-08-08T22:00:00+00:00", 4200.0),
    )
    series = build_trajectory(forecast, history_prices=history)

    assert series.history[0][0] == 0.0
    assert series.history[-1][0] == 50.0
    assert series.history_gap is False
    assert series.base[0] == (50.0, 0.0)
    assert series.base[-1][0] == 100.0
    assert series.bull[-1][1] == 1.5
    assert series.bear[-1][1] == 0.5


def test_stale_history_stops_before_now_and_marks_price_gap():
    forecast = _forecast(as_of="2026-08-09T22:00:00+00:00")
    history = (
        ("2026-08-07T18:00:00+00:00", 4160.0),
        ("2026-08-07T20:00:00+00:00", 4200.0),
    )

    series = build_trajectory(forecast, history_prices=history)
    svg = render_forecast_svg(forecast, history_prices=history)

    assert series.history_gap is True
    assert series.history[-1][0] == 45.0
    assert series.base[0][0] == 50.0
    assert "ingen nye prisdata" in svg


def test_unstable_regime_selects_impulse_reversal_profile():
    series = build_trajectory(
        _forecast(),
        market_regime="BULLISH · MEDIUM · Kort og skiftende regime",
    )

    assert series.profile == "IMPULSE_REVERSAL"
    midpoint = series.base[len(series.base) // 2][1]
    assert midpoint > series.base[-1][1]


def test_neutral_low_volatility_selects_squeeze():
    series = build_trajectory(
        _forecast(direction="NEUTRAL", expected_move_low_pct=-0.4, expected_move_high_pct=0.4),
        volatility_score=0.1,
    )

    assert series.profile == "SQUEEZE"


def test_svg_marks_now_fan_and_scenarios_without_svg_text_nodes():
    svg = render_forecast_svg(
        _forecast(status="DEGRADED", missing_inputs=("news_context",)),
        history_prices=(("2026-08-08T22:00:00+00:00", 4200.0),),
    )

    assert 'class="pg-now"' in svg
    assert 'class="pg-fan"' in svg
    assert svg.count('class="pg-alt ') == 2
    assert 'class="pg-base"' in svg
    assert 'class="pg-alt pg-bull"' in svg
    assert 'class="pg-alt pg-bear"' in svg
    assert "#2f9e64" in svg
    assert "#d15b5b" in svg
    assert "#374151" in svg
    assert "DEGRADED" in svg
    assert "news_context" in svg
    assert "historikk" in svg
    assert "prognose" in svg
    assert "<text" not in svg
