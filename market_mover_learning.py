from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import connect
from market_history_store import MarketHistoryStore
from market_mover_observation import observe_market_mover
from state_contracts import MarketMoverAlert


MARKET_MOVER_LEARNING_VERSION = "market-mover-learning-v1"


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MarketMoverOutcome:
    alert_id: str
    event_cluster_id: str
    market: str
    alert_created_at: str
    evaluated_at: str
    status: str
    severity: str
    expected_direction: str
    expected_move_low_pct: float
    expected_move_high_pct: float
    horizon_hours: float
    source_quality: float
    novelty: float
    context_multiplier: float
    observed_move_pct: float | None
    time_to_peak_minutes: int | None
    peak_at: str | None
    direction_hit: bool | None
    expected_range_reached: bool | None
    peak_within_expected_interval: bool | None
    engine_version: str = MARKET_MOVER_LEARNING_VERSION

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class MarketMoverOutcomeStore:
    """Persistent learning population for high-significance market-mover alerts."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_mover_outcomes (
                    alert_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    alert_created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_market_mover_outcome_market_created
                ON market_mover_outcomes(market, alert_created_at);
                """
            )

    def save(self, outcome: MarketMoverOutcome) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO market_mover_outcomes(
                    alert_id, market, alert_created_at, status, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    market=excluded.market,
                    alert_created_at=excluded.alert_created_at,
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    outcome.alert_id,
                    outcome.market,
                    outcome.alert_created_at,
                    outcome.status,
                    json.dumps(outcome.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_all(self, *, market: str | None = None, limit: int = 500) -> list[MarketMoverOutcome]:
        query = "SELECT payload_json FROM market_mover_outcomes"
        params: list[Any] = []
        if market:
            query += " WHERE market=?"
            params.append(str(market))
        query += " ORDER BY alert_created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with connect(self.path) as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [MarketMoverOutcome(**json.loads(row["payload_json"])) for row in rows]


def _load_alerts(path: str | Path, *, limit: int = 500) -> list[MarketMoverAlert]:
    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM market_mover_alerts
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    except Exception:
        return []
    return [MarketMoverAlert(**json.loads(row["payload_json"])) for row in rows]


def _direction_hit(direction: str, move_pct: float) -> bool | None:
    direction = str(direction).upper()
    if direction == "UP":
        return move_pct > 0.0
    if direction == "DOWN":
        return move_pct < 0.0
    if direction == "UNCERTAIN":
        return None
    return None


def _range_flags(alert: MarketMoverAlert, move_pct: float) -> tuple[bool, bool]:
    low = min(float(alert.expected_move_low_pct), float(alert.expected_move_high_pct))
    high = max(float(alert.expected_move_low_pct), float(alert.expected_move_high_pct))
    within = low <= move_pct <= high
    direction = str(alert.expected_direction).upper()
    if direction == "UP":
        positive_targets = [value for value in (low, high) if value > 0.0]
        threshold = min(positive_targets) if positive_targets else max(0.0, low)
        reached = move_pct >= threshold
    elif direction == "DOWN":
        negative_targets = [value for value in (low, high) if value < 0.0]
        threshold = max(negative_targets) if negative_targets else min(0.0, high)
        reached = move_pct <= threshold
    else:
        target = min(abs(low), abs(high))
        reached = abs(move_pct) >= target
    return reached, within


def evaluate_market_mover(
    path: str | Path,
    alert: MarketMoverAlert,
    *,
    evaluated_at: datetime | None = None,
) -> MarketMoverOutcome:
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observation = observe_market_mover(alert, MarketHistoryStore(path), now=now)

    if observation is None:
        status = "PENDING"
        observed_move = None
        elapsed = None
        peak_at = None
        direction_hit = None
        range_reached = None
        within = None
    else:
        status = "COMPLETE" if observation.observation_complete else "PARTIAL"
        observed_move = float(observation.move_pct)
        elapsed = int(observation.elapsed_minutes)
        peak_at = observation.peak_at
        direction_hit = _direction_hit(alert.expected_direction, observed_move)
        range_reached, within = _range_flags(alert, observed_move)

    return MarketMoverOutcome(
        alert_id=alert.alert_id,
        event_cluster_id=alert.event_cluster_id,
        market=alert.market,
        alert_created_at=alert.created_at,
        evaluated_at=now.isoformat(),
        status=status,
        severity=alert.severity,
        expected_direction=alert.expected_direction,
        expected_move_low_pct=float(alert.expected_move_low_pct),
        expected_move_high_pct=float(alert.expected_move_high_pct),
        horizon_hours=float(alert.horizon_hours),
        source_quality=float(alert.source_quality),
        novelty=float(alert.novelty),
        context_multiplier=float(alert.context_multiplier),
        observed_move_pct=None if observed_move is None else round(observed_move, 6),
        time_to_peak_minutes=elapsed,
        peak_at=peak_at,
        direction_hit=direction_hit,
        expected_range_reached=range_reached,
        peak_within_expected_interval=within,
    )


def refresh_market_mover_outcomes(
    path: str | Path = "pricegauger.db",
    *,
    limit: int = 500,
) -> list[MarketMoverOutcome]:
    store = MarketMoverOutcomeStore(path)
    outcomes: list[MarketMoverOutcome] = []
    for alert in _load_alerts(path, limit=limit):
        outcome = evaluate_market_mover(path, alert)
        store.save(outcome)
        outcomes.append(outcome)
    return outcomes
