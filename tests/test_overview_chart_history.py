from __future__ import annotations

import json

from database import connect
from forecast_contracts import ForecastSnapshot
from forecast_timeline import render_forecast_timeline_svg
from overview_chart_history import history_days_for_horizon, load_overview_chart_history


def test_history_span_scales_with_forecast_horizon():
    assert history_days_for_horizon(5.0 / 60.0) == 7
    assert history_days_for_horizon(1.0) == 30
    assert history_days_for_horizon(4.0) == 90
    assert history_days_for_horizon(24.0) == 180
    assert history_days_for_horizon(168.0) == 365


def test_long_chart_history_uses_sparse_context_and_recent_canonical_edge(tmp_path):
    db = tmp_path / "history.db"
    with connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE technical_market_state_snapshots (
                snapshot_id TEXT PRIMARY KEY, market TEXT NOT NULL, as_of TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE realtime_bars_1m (
                bar_id TEXT PRIMARY KEY, market TEXT NOT NULL, bar_time TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            """
        )
        for index, (stamp, price) in enumerate(
            [
                ("2026-05-15T12:00:00+00:00", 80.0),
                ("2026-06-15T12:00:00+00:00", 84.0),
                ("2026-07-15T12:00:00+00:00", 88.0),
                ("2026-08-11T12:00:00+00:00", 89.0),
            ]
        ):
            conn.execute(
                "INSERT INTO technical_market_state_snapshots VALUES (?, ?, ?, ?)",
                (f"t{index}", "Brent", stamp, json.dumps({"as_of": stamp, "price": price})),
            )
        for index, (stamp, price) in enumerate(
            [
                ("2026-08-12T10:00:00+00:00", 90.0),
                ("2026-08-12T11:00:00+00:00", 91.0),
                ("2026-08-12T12:00:00+00:00", 92.0),
            ]
        ):
            conn.execute(
                "INSERT INTO realtime_bars_1m VALUES (?, ?, ?, ?)",
                (f"r{index}", "Brent", stamp, json.dumps({"bar_time": stamp, "close": price})),
            )

    points = load_overview_chart_history(
        db,
        market="Brent",
        as_of="2026-08-12T12:00:00+00:00",
        horizon_hours=4.0,
        technical_limit=100,
        recent_1m_limit=100,
    )

    assert points[0] == ("2026-05-15T12:00:00+00:00", 80.0)
    assert points[-1] == ("2026-08-12T12:00:00+00:00", 92.0)
    assert len(points) == 7


def test_timeline_reserves_forecast_space_when_history_is_long():
    forecast = ForecastSnapshot(
        forecast_id="forecast:history-split",
        market="Brent",
        as_of="2026-08-12T12:00:00+00:00",
        reference_price=90.0,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.6,
        expected_move_low_pct=0.5,
        expected_move_high_pct=1.5,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:history-split",
        information_snapshot_id="information:history-split",
        market_snapshot_id="market:history-split",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )
    html = render_forecast_timeline_svg(
        [forecast],
        observed_prices=[
            ("2026-05-15T12:00:00+00:00", 80.0),
            ("2026-07-15T12:00:00+00:00", 88.0),
            ("2026-08-12T12:00:00+00:00", 90.0),
        ],
        now=None,
    )

    assert "NÅ · observert til venstre, prognose til høyre" in html
    assert "HISTORIKK · FASIT" in html
    assert "NÅ → PROGNOSE" in html
    # The split is deliberately reserved at x=64 rather than being crushed
    # against the right edge by months of calendar history.
    assert 'x1="64.0"' in html
