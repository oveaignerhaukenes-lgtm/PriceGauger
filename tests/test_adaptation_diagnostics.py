import json
from pathlib import Path

from adaptation_diagnostics import load_adaptation_contexts
from database import connect
from forecast_error import ForecastErrorObservation


def _error(*, error_id: str = "error:1", market: str = "Silver") -> ForecastErrorObservation:
    return ForecastErrorObservation(
        error_id=error_id,
        forecast_id="forecast:1",
        market=market,
        horizon_hours=1.0,
        forecast_as_of="2026-08-12T10:00:00+00:00",
        outcome_evaluated_at="2026-08-12T11:00:00+00:00",
        expected_low_pct=-0.2,
        expected_high_pct=0.4,
        expected_center_pct=0.1,
        expected_half_width_pct=0.3,
        realized_move_pct=-0.5,
        signed_center_error_pct=-0.6,
        normalized_center_error=-2.0,
        signed_interval_error_pct=-0.3,
        normalized_interval_error=-1.0,
        interval_hit=False,
        direction_hit=False,
        classification="DIRECTION_MISS",
    )


def _seed(path: Path) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE response_divergence_snapshots (
                divergence_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                window TEXT NOT NULL,
                as_of TEXT NOT NULL,
                information_snapshot_id TEXT NOT NULL,
                cross_market_snapshot_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE transmission_state_snapshots (
                transmission_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                window TEXT NOT NULL,
                as_of TEXT NOT NULL,
                response_divergence_id TEXT NOT NULL,
                resolution_status TEXT NOT NULL,
                dominant_channel TEXT,
                payload_json TEXT NOT NULL
            );
            """
        )
        response_rows = [
            ("d-before", "2026-08-12T09:59:00+00:00", "DIVERGENT"),
            ("d-live", "2026-08-12T10:20:00+00:00", "DIVERGENT"),
            ("a-live", "2026-08-12T10:45:00+00:00", "ALIGNED"),
            ("d-after", "2026-08-12T11:01:00+00:00", "DIVERGENT"),
        ]
        for divergence_id, as_of, status in response_rows:
            payload = {
                "divergence_id": divergence_id,
                "market": "Silver",
                "window": "15m",
                "as_of": as_of,
                "status": status,
            }
            db.execute(
                "INSERT INTO response_divergence_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (divergence_id, "Silver", "15m", as_of, "info", "cross", status, json.dumps(payload)),
            )

        transmission_rows = [
            ("t1", "2026-08-12T10:21:00+00:00", "UNRESOLVED", None),
            ("t2", "2026-08-12T10:46:00+00:00", "RESOLVED", "RATES_FX"),
        ]
        for transmission_id, as_of, resolution, channel in transmission_rows:
            payload = {
                "transmission_id": transmission_id,
                "market": "Silver",
                "window": "15m",
                "as_of": as_of,
                "resolution_status": resolution,
                "dominant_channel": channel,
            }
            db.execute(
                "INSERT INTO transmission_state_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (transmission_id, "Silver", "15m", as_of, "d-live", resolution, channel, json.dumps(payload)),
            )


def test_context_uses_only_observations_while_forecast_was_alive(tmp_path):
    path = tmp_path / "diagnostics.db"
    _seed(path)

    contexts = load_adaptation_contexts(path, (_error(),))
    context = contexts["error:1"]

    assert context.response_count == 2
    assert context.divergent_count == 1
    assert context.aligned_count == 1
    assert context.saw_divergence is True
    assert context.transmission_count == 2
    assert context.resolved_count == 1
    assert context.unresolved_count == 1
    assert context.saw_unresolved_transmission is True
    assert context.dominant_channels == ("RATES_FX",)


def test_context_is_market_bound(tmp_path):
    path = tmp_path / "diagnostics.db"
    _seed(path)

    context = load_adaptation_contexts(path, (_error(market="Gold"),))["error:1"]

    assert context.response_count == 0
    assert context.transmission_count == 0
    assert context.has_context is False


def test_missing_observation_tables_degrade_to_empty_context(tmp_path):
    path = tmp_path / "diagnostics.db"

    context = load_adaptation_contexts(path, (_error(),))["error:1"]

    assert context.response_count == 0
    assert context.transmission_count == 0
