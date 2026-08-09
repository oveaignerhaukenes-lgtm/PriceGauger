from __future__ import annotations

import json

from database import connect
from forecast_contracts import ForecastSnapshot
from forecast_learning import evaluate_forecast
from market_history_store import MarketHistoryStore
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore


def _technical_table(path) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS technical_market_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                market TEXT NOT NULL,
                as_of TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )


def _technical_point(path, *, market: str, stamp: str, price: float) -> None:
    _technical_table(path)
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO technical_market_state_snapshots(snapshot_id, market, as_of, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                f"{market}:{stamp}",
                market,
                stamp,
                json.dumps({"market": market, "as_of": stamp, "price": price}),
            ),
        )


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


def test_market_history_merges_legacy_snapshots_and_prefers_realtime_overlap(tmp_path):
    path = tmp_path / "history.db"
    _technical_point(path, market="Gold", stamp="2026-08-09T10:00:00+00:00", price=100.0)
    _technical_point(path, market="Gold", stamp="2026-08-09T10:01:00+00:00", price=101.0)
    _bar(path, market="Gold", stamp="2026-08-09T10:01:00+00:00", price=111.0)
    _bar(path, market="Gold", stamp="2026-08-09T10:02:00+00:00", price=112.0)

    points = MarketHistoryStore(path).load_range(
        market="Gold",
        start="2026-08-09T10:00:00+00:00",
        end="2026-08-09T10:03:00+00:00",
    )

    assert points == (
        ("2026-08-09T10:00:00+00:00", 100.0),
        ("2026-08-09T10:01:00+00:00", 111.0),
        ("2026-08-09T10:02:00+00:00", 112.0),
    )


def test_forecast_learning_uses_realtime_bars_without_technical_snapshots(tmp_path):
    path = tmp_path / "learning.db"
    _bar(path, market="Gold", stamp="2026-08-09T10:05:00+00:00", price=101.0)
    _bar(path, market="Gold", stamp="2026-08-09T10:10:00+00:00", price=102.0)
    _bar(path, market="Gold", stamp="2026-08-09T10:15:00+00:00", price=103.0)

    forecast = ForecastSnapshot(
        forecast_id="forecast:test",
        market="Gold",
        as_of="2026-08-09T10:00:00+00:00",
        reference_price=100.0,
        direction="LONG_BIAS",
        direction_score=0.8,
        confidence=0.8,
        expected_move_low_pct=1.0,
        expected_move_high_pct=4.0,
        horizon_hours=0.25,
        time_scale="MINUTES",
        decision_snapshot_id="decision:test",
        information_snapshot_id="information:test",
        market_snapshot_id="market:test",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )

    outcome = evaluate_forecast(path, forecast)

    assert outcome.status == "COMPLETE"
    assert outcome.sample_count == 3
    assert outcome.last_observed_at == "2026-08-09T10:15:00+00:00"
    assert outcome.last_price == 103.0
    assert outcome.realized_move_pct == 3.0
    assert outcome.direction_hit is True
    assert outcome.interval_hit is True
