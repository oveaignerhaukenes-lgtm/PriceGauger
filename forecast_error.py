from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from database import connect
from forecast_learning import ForecastOutcome, ForecastOutcomeStore


FORECAST_ERROR_VERSION = "forecast-error-v1"
ERROR_CLASSES = {"IN_INTERVAL", "DIRECTION_ONLY", "DIRECTION_MISS", "UNCONFIRMED"}


def _error_id(forecast_id: str) -> str:
    digest = sha256(f"{forecast_id}|{FORECAST_ERROR_VERSION}".encode("utf-8")).hexdigest()[:24]
    return f"forecast-error:{digest}"


@dataclass(frozen=True, slots=True)
class ForecastErrorObservation:
    error_id: str
    forecast_id: str
    market: str
    horizon_hours: float
    forecast_as_of: str
    outcome_evaluated_at: str
    expected_low_pct: float
    expected_high_pct: float
    expected_center_pct: float
    expected_half_width_pct: float
    realized_move_pct: float
    signed_center_error_pct: float
    normalized_center_error: float | None
    signed_interval_error_pct: float
    normalized_interval_error: float | None
    interval_hit: bool | None
    direction_hit: bool | None
    classification: str
    scoring_version: str = FORECAST_ERROR_VERSION

    def __post_init__(self) -> None:
        if self.classification not in ERROR_CLASSES:
            raise ValueError(f"unsupported forecast error class: {self.classification}")
        if self.horizon_hours <= 0:
            raise ValueError("forecast error horizon must be positive")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def build_forecast_error(outcome: ForecastOutcome) -> ForecastErrorObservation | None:
    """Freeze one descriptive error observation from a COMPLETE forecast outcome.

    ``normalized_center_error`` places the realized move relative to the frozen
    forecast interval: 0 is the interval centre and +/-1 are its bounds.
    ``normalized_interval_error`` is zero while realization remains inside the
    interval and measures only the signed miss outside it. No causal explanation
    or corrective weight is inferred here.
    """
    if outcome.status != "COMPLETE" or outcome.horizon_hours is None:
        return None
    if outcome.realized_move_pct is None:
        return None
    if outcome.expected_move_low_pct is None or outcome.expected_move_high_pct is None:
        return None

    low = float(outcome.expected_move_low_pct)
    high = float(outcome.expected_move_high_pct)
    if low > high:
        low, high = high, low
    realized = float(outcome.realized_move_pct)
    center = (low + high) / 2.0
    half_width = (high - low) / 2.0
    signed_center = realized - center
    normalized_center = None if half_width <= 1e-12 else signed_center / half_width

    if realized < low:
        interval_error = realized - low
    elif realized > high:
        interval_error = realized - high
    else:
        interval_error = 0.0
    normalized_interval = None if half_width <= 1e-12 else interval_error / half_width

    if outcome.interval_hit is True:
        classification = "IN_INTERVAL"
    elif outcome.direction_hit is True:
        classification = "DIRECTION_ONLY"
    elif outcome.direction_hit is False:
        classification = "DIRECTION_MISS"
    else:
        classification = "UNCONFIRMED"

    return ForecastErrorObservation(
        error_id=_error_id(outcome.forecast_id),
        forecast_id=outcome.forecast_id,
        market=outcome.market,
        horizon_hours=float(outcome.horizon_hours),
        forecast_as_of=outcome.forecast_as_of,
        outcome_evaluated_at=outcome.evaluated_at,
        expected_low_pct=round(low, 6),
        expected_high_pct=round(high, 6),
        expected_center_pct=round(center, 6),
        expected_half_width_pct=round(half_width, 6),
        realized_move_pct=round(realized, 6),
        signed_center_error_pct=round(signed_center, 6),
        normalized_center_error=None if normalized_center is None else round(normalized_center, 6),
        signed_interval_error_pct=round(interval_error, 6),
        normalized_interval_error=None if normalized_interval is None else round(normalized_interval, 6),
        interval_hit=outcome.interval_hit,
        direction_hit=outcome.direction_hit,
        classification=classification,
    )


class ForecastErrorStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_error_observations (
                    error_id TEXT PRIMARY KEY,
                    forecast_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    horizon_hours REAL NOT NULL,
                    forecast_as_of TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_error_market_horizon_as_of
                ON forecast_error_observations(market, horizon_hours, forecast_as_of);
                """
            )

    def save(self, observation: ForecastErrorObservation) -> bool:
        payload = json.dumps(observation.to_record(), ensure_ascii=False, sort_keys=True)
        with connect(self.path) as db:
            cursor = db.execute(
                """
                INSERT INTO forecast_error_observations(
                    error_id, forecast_id, market, horizon_hours, forecast_as_of, classification, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(error_id) DO NOTHING
                """,
                (
                    observation.error_id,
                    observation.forecast_id,
                    observation.market,
                    observation.horizon_hours,
                    observation.forecast_as_of,
                    observation.classification,
                    payload,
                ),
            )
            return bool(getattr(cursor, "rowcount", 0))

    def load_all(
        self,
        *,
        market: str | None = None,
        horizon_hours: float | None = None,
        limit: int = 1000,
    ) -> list[ForecastErrorObservation]:
        clauses: list[str] = []
        params: list[object] = []
        if market is not None:
            clauses.append("market=?")
            params.append(str(market))
        if horizon_hours is not None:
            clauses.append("ABS(horizon_hours - ?) < 0.000001")
            params.append(float(horizon_hours))
        query = "SELECT payload_json FROM forecast_error_observations"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY forecast_as_of DESC, error_id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with connect(self.path) as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [ForecastErrorObservation(**json.loads(row["payload_json"])) for row in rows]


def refresh_forecast_errors(
    path: str | Path = "pricegauger.db",
    *,
    outcomes: Iterable[ForecastOutcome] | None = None,
    limit: int = 2000,
) -> list[ForecastErrorObservation]:
    source = list(outcomes) if outcomes is not None else ForecastOutcomeStore(path).load_all(limit=limit)
    store = ForecastErrorStore(path)
    inserted: list[ForecastErrorObservation] = []
    for outcome in source:
        observation = build_forecast_error(outcome)
        if observation is not None and store.save(observation):
            inserted.append(observation)
    return inserted
