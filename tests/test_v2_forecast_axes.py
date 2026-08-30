from __future__ import annotations

from types import SimpleNamespace

from v2_forecast_visualization import (
    _price_axis_label,
    _relative_horizon_label,
    render_v2_forecast_chart,
)


def _view(**changes):
    values = dict(
        price_history=(
            ("2026-08-30T18:00:00+00:00", 4400.0),
            ("2026-08-30T19:00:00+00:00", 4410.0),
        ),
        forecast_ghosts=(),
        expected_return=0.01,
        lower_return=-0.005,
        upper_return=0.02,
        baseline_return=0.01,
        path_profile=(),
        path_shape="DRIFT",
        applied_layers=(),
        recipe_label="TA-only · recipe 1 (v2)",
        feed_delay_minutes=0,
        horizon_seconds=4 * 3600,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def test_forecast_chart_has_compact_time_and_price_axes():
    html = render_v2_forecast_chart(_view())

    assert 'class="pg-v2-price-axis"' in html
    assert 'aria-label="Prisakse"' in html
    assert 'class="pg-v2-time-axis"' in html
    assert 'aria-label="Prognosehorisont"' in html
    assert '>NÅ<' in html
    assert '>+2t<' in html
    assert '>+4t<' in html


def test_axis_labels_remain_compact_across_horizons_and_prices():
    assert _relative_horizon_label(15 * 60) == "+15m"
    assert _relative_horizon_label(4 * 3600) == "+4t"
    assert _relative_horizon_label(7 * 86400) == "+7d"
    assert _price_axis_label(4512.8) == "4 513"
    assert _price_axis_label(68.125) == "68.12"
