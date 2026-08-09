from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import connect
from forecast_contracts import FORECAST_ENGINE_VERSION, ForecastSnapshot


LEARNING_ENGINE_VERSION = "forecast-learning-v1"


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ForecastOutcome:
    forecast_id: str
    market: str
    forecast_as_of: str
    evaluated_at: str
    status: str
    progress: float
    horizon_hours: float | None
    reference_price: float | None
    last_observed_at: str | None
    last_price: float | None
    realized_move_pct: float | None
    expected_move_low_pct: float | None
    expected_move_high_pct: float | None
    interval_hit: bool | None
    direction_hit: bool | None
    max_up_pct: float | None
    max_down_pct: float | None
    mfe_pct: float | None
    mae_pct: float | None
    sample_count: int
    engine_version: str = LEARNING_ENGINE_VERSION

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class ForecastOutcomeStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_outcomes (
                    forecast_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    forecast_as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_outcome_market_as_of
                ON forecast_outcomes(market, forecast_as_of);
                """
            )

    def save(self, outcome: ForecastOutcome) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO forecast_outcomes(
                    forecast_id, market, forecast_as_of, status, progress, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(forecast_id) DO UPDATE SET
                    market=excluded.market,
                    forecast_as_of=excluded.forecast_as_of,
                    status=excluded.status,
                    progress=excluded.progress,
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    outcome.forecast_id,
                    outcome.market,
                    outcome.forecast_as_of,
                    outcome.status,
                    outcome.progress,
                    json.dumps(outcome.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_all(self, *, market: str | None = None, limit: int = 500) -> list[ForecastOutcome]:
        query = "SELECT payload_json FROM forecast_outcomes"
        params: list[Any] = []
        if market:
            query += " WHERE market=?"
            params.append(market)
        query += " ORDER BY forecast_as_of DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with connect(self.path) as db:
            rows = db.execute(query, tuple(params)).fetchall()
        return [ForecastOutcome(**json.loads(row["payload_json"])) for row in rows]


def _load_forecasts(path: str | Path, *, limit: int = 500) -> list[ForecastSnapshot]:
    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM forecast_snapshots
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
    except Exception:
        return []

    forecasts: list[ForecastSnapshot] = []
    for row in rows:
        record = json.loads(row["payload_json"])
        if str(record.get("engine_version") or "") != FORECAST_ENGINE_VERSION:
            continue
        record["missing_inputs"] = tuple(record.get("missing_inputs") or ())
        forecasts.append(ForecastSnapshot(**record))
    return forecasts


def _market_points(
    path: str | Path,
    *,
    forecast: ForecastSnapshot,
    limit: int = 2000,
) -> list[tuple[datetime, float]]:
    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM technical_market_state_snapshots
                WHERE market=? AND as_of>=?
                ORDER BY as_of ASC
                LIMIT ?
                """,
                (forecast.market, forecast.as_of, max(2, int(limit))),
            ).fetchall()
    except Exception:
        return []

    points: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for row in rows:
        record = json.loads(row["payload_json"])
        price = record.get("price")
        stamp = str(record.get("as_of") or "")
        if price is None or not stamp:
            continue
        try:
            observed = _utc(stamp)
        except (TypeError, ValueError):
            continue
        if observed in seen:
            continue
        seen.add(observed)
        points.append((observed, float(price)))
    return points


def _active_path(
    forecast: ForecastSnapshot,
    points: list[tuple[datetime, float]],
    *,
    max_active_gap_minutes: float = 30.0,
) -> tuple[list[tuple[datetime, float]], float, bool]:
    if not points or forecast.horizon_hours is None:
        return [], 0.0, False
    target_seconds = max(0.25, float(forecast.horizon_hours)) * 3600.0
    max_gap = max(60.0, float(max_active_gap_minutes) * 60.0)
    cursor = _utc(forecast.as_of)
    active_seconds = 0.0
    selected: list[tuple[datetime, float]] = []
    for observed, price in points:
        gap = max(0.0, (observed - cursor).total_seconds())
        if gap <= max_gap:
            active_seconds += gap
        selected.append((observed, price))
        cursor = observed
        if active_seconds >= target_seconds:
            break
    return selected, min(1.0, active_seconds / target_seconds), active_seconds >= target_seconds


def realized_path(
    path: str | Path,
    forecast: ForecastSnapshot,
) -> tuple[tuple[str, float], ...]:
    selected, _, _ = _active_path(forecast, _market_points(path, forecast=forecast))
    return tuple((stamp.isoformat(), price) for stamp, price in selected)


def realized_progress_path(
    path: str | Path,
    forecast: ForecastSnapshot,
    *,
    max_active_gap_minutes: float = 30.0,
) -> tuple[tuple[float, float], ...]:
    """Return realized move as active-horizon progress for forecast overlays.

    X is 0..1 through the forecast horizon using active trading time; Y is the
    realized percentage move from the frozen reference price. Closed-market gaps
    do not stretch the overlay horizontally.
    """
    if forecast.reference_price is None or forecast.horizon_hours is None:
        return ()
    points = _market_points(path, forecast=forecast)
    if not points:
        return ()
    target_seconds = max(0.25, float(forecast.horizon_hours)) * 3600.0
    max_gap = max(60.0, float(max_active_gap_minutes) * 60.0)
    cursor = _utc(forecast.as_of)
    active_seconds = 0.0
    ref = float(forecast.reference_price)
    result: list[tuple[float, float]] = [(0.0, 0.0)]
    for observed, price in points:
        gap = max(0.0, (observed - cursor).total_seconds())
        if gap <= max_gap:
            active_seconds += gap
        progress = min(1.0, active_seconds / target_seconds)
        move = ((float(price) / ref) - 1.0) * 100.0
        result.append((progress, move))
        cursor = observed
        if active_seconds >= target_seconds:
            break
    return tuple(result)


def evaluate_forecast(
    path: str | Path,
    forecast: ForecastSnapshot,
    *,
    evaluated_at: datetime | None = None,
) -> ForecastOutcome:
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ref = forecast.reference_price
    selected, progress, complete = _active_path(
        forecast,
        _market_points(path, forecast=forecast),
    )

    if ref is None or forecast.horizon_hours is None:
        status = "WAITING_FOR_FORECAST_INPUTS"
    elif not selected:
        status = "PENDING"
    elif complete:
        status = "COMPLETE"
    else:
        status = "PARTIAL"

    last_at = selected[-1][0].isoformat() if selected else None
    last_price = selected[-1][1] if selected else None
    realized = ((last_price / ref) - 1.0) * 100.0 if ref and last_price is not None else None

    moves = [((price / ref) - 1.0) * 100.0 for _, price in selected] if ref else []
    max_up = max(moves) if moves else None
    max_down = min(moves) if moves else None

    mfe = mae = None
    if moves:
        if forecast.direction == "LONG_BIAS":
            mfe, mae = max_up, max_down
        elif forecast.direction == "SHORT_BIAS":
            mfe, mae = -max_down, -max_up

    interval_hit = direction_hit = None
    if complete and realized is not None:
        low = forecast.expected_move_low_pct
        high = forecast.expected_move_high_pct
        if low is not None and high is not None:
            interval_hit = float(low) <= realized <= float(high)
        if forecast.direction == "LONG_BIAS":
            direction_hit = realized > 0.0
        elif forecast.direction == "SHORT_BIAS":
            direction_hit = realized < 0.0
        elif forecast.direction in {"NEUTRAL", "CONFLICTED", "INSUFFICIENT_DATA"}:
            direction_hit = bool(interval_hit) if interval_hit is not None else abs(realized) <= 0.25

    return ForecastOutcome(
        forecast_id=forecast.forecast_id,
        market=forecast.market,
        forecast_as_of=forecast.as_of,
        evaluated_at=now.isoformat(),
        status=status,
        progress=round(progress, 4),
        horizon_hours=forecast.horizon_hours,
        reference_price=ref,
        last_observed_at=last_at,
        last_price=last_price,
        realized_move_pct=None if realized is None else round(realized, 6),
        expected_move_low_pct=forecast.expected_move_low_pct,
        expected_move_high_pct=forecast.expected_move_high_pct,
        interval_hit=interval_hit,
        direction_hit=direction_hit,
        max_up_pct=None if max_up is None else round(max_up, 6),
        max_down_pct=None if max_down is None else round(max_down, 6),
        mfe_pct=None if mfe is None else round(mfe, 6),
        mae_pct=None if mae is None else round(mae, 6),
        sample_count=len(selected),
    )


def refresh_forecast_outcomes(
    path: str | Path = "pricegauger.db",
    *,
    limit: int = 500,
) -> list[ForecastOutcome]:
    store = ForecastOutcomeStore(path)
    outcomes: list[ForecastOutcome] = []
    for forecast in _load_forecasts(path, limit=limit):
        outcome = evaluate_forecast(path, forecast)
        store.save(outcome)
        outcomes.append(outcome)
    return outcomes
