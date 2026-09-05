from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from database import connect
from spring_trade_engine.contracts import SpringObservationV1
from spring_trade_engine.contracts.evaluation import (
    SpringEpisodeCandidateV1,
    SpringForwardLabelV1,
    SpringRuntimeCoverageV1,
    SpringTurningPointV1,
)
from spring_trade_engine.persistence.store import MODEL_VERSION


EVALUATION_VERSION = "spring-evaluation-v1"


@dataclass(frozen=True, slots=True)
class SpringForwardLabelSeedV1:
    instrument_id: int
    observed_at: datetime
    close_price: float


def ensure_spring_evaluation_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_spring_turning_points (
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                observed_at TIMESTAMPTZ NOT NULL,
                model_version TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('TURN_UP','TURN_DOWN')),
                close_price DOUBLE PRECISION NOT NULL,
                displacement_pct DOUBLE PRECISION NOT NULL,
                shock_score DOUBLE PRECISION NOT NULL,
                energy_proxy DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (instrument_id, observed_at, model_version)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_spring_episode_candidates (
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                observed_at TIMESTAMPTZ NOT NULL,
                model_version TEXT NOT NULL,
                close_price DOUBLE PRECISION NOT NULL,
                displacement_pct DOUBLE PRECISION NOT NULL,
                shock_score DOUBLE PRECISION NOT NULL,
                energy_proxy DOUBLE PRECISION NOT NULL,
                trigger_rule TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (instrument_id, observed_at, model_version)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_spring_forward_labels (
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                observed_at TIMESTAMPTZ NOT NULL,
                model_version TEXT NOT NULL,
                evaluation_version TEXT NOT NULL,
                horizon_minutes INTEGER NOT NULL CHECK (horizon_minutes > 0),
                realized_at TIMESTAMPTZ NOT NULL,
                return_pct DOUBLE PRECISION NOT NULL,
                max_up_excursion_pct DOUBLE PRECISION NOT NULL,
                max_down_excursion_pct DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (instrument_id, observed_at, model_version, evaluation_version, horizon_minutes)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_spring_runtime_coverage (
                cycle_started_at TIMESTAMPTZ NOT NULL,
                evaluation_version TEXT NOT NULL,
                cycle_finished_at TIMESTAMPTZ NOT NULL,
                active_instruments INTEGER NOT NULL,
                observations_persisted INTEGER NOT NULL,
                instruments_skipped INTEGER NOT NULL,
                failures INTEGER NOT NULL,
                forward_labels_persisted INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (cycle_started_at, evaluation_version)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_spring_labels_instrument_time_idx
            ON pg_v2_spring_forward_labels(instrument_id, observed_at DESC, horizon_minutes)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_spring_episode_candidates_time_idx
            ON pg_v2_spring_episode_candidates(instrument_id, observed_at DESC)
            """
        )


def persist_turning_point_v1(point: SpringTurningPointV1) -> int:
    if point.direction not in {"TURN_UP", "TURN_DOWN"}:
        raise ValueError("Spring turning point must be TURN_UP or TURN_DOWN")
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO pg_v2_spring_turning_points(
                instrument_id, observed_at, model_version, direction, close_price,
                displacement_pct, shock_score, energy_proxy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_id, observed_at, model_version) DO NOTHING
            """,
            (
                point.instrument_id, point.observed_at, MODEL_VERSION, point.direction,
                point.close_price, point.displacement_pct, point.shock_score, point.energy_proxy,
            ),
        )
        return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def persist_episode_candidate_v1(candidate: SpringEpisodeCandidateV1) -> int:
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO pg_v2_spring_episode_candidates(
                instrument_id, observed_at, model_version, close_price,
                displacement_pct, shock_score, energy_proxy, trigger_rule
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_id, observed_at, model_version) DO NOTHING
            """,
            (
                candidate.instrument_id, candidate.observed_at, MODEL_VERSION,
                candidate.close_price, candidate.displacement_pct, candidate.shock_score,
                candidate.energy_proxy, candidate.trigger_rule,
            ),
        )
        return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def persist_forward_label_v1(label: SpringForwardLabelV1) -> int:
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO pg_v2_spring_forward_labels(
                instrument_id, observed_at, model_version, evaluation_version,
                horizon_minutes, realized_at, return_pct,
                max_up_excursion_pct, max_down_excursion_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                instrument_id, observed_at, model_version, evaluation_version, horizon_minutes
            ) DO NOTHING
            """,
            (
                label.instrument_id, label.observed_at, MODEL_VERSION, EVALUATION_VERSION,
                label.horizon_minutes, label.realized_at, label.return_pct,
                label.max_up_excursion_pct, label.max_down_excursion_pct,
            ),
        )
        return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def persist_runtime_coverage_v1(coverage: SpringRuntimeCoverageV1) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_spring_runtime_coverage(
                cycle_started_at, evaluation_version, cycle_finished_at,
                active_instruments, observations_persisted, instruments_skipped,
                failures, forward_labels_persisted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (cycle_started_at, evaluation_version) DO NOTHING
            """,
            (
                coverage.cycle_started_at, EVALUATION_VERSION, coverage.cycle_finished_at,
                coverage.active_instruments, coverage.observations_persisted,
                coverage.instruments_skipped, coverage.failures,
                coverage.forward_labels_persisted,
            ),
        )


def load_pending_forward_label_seeds_v1(
    *,
    horizon_minutes: int,
    eligible_before: datetime,
    limit: int = 100,
) -> tuple[SpringForwardLabelSeedV1, ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT o.instrument_id, o.observed_at, o.close_price
            FROM pg_v2_spring_observations o
            WHERE o.model_version = ?
              AND o.observed_at <= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_v2_spring_forward_labels l
                  WHERE l.instrument_id = o.instrument_id
                    AND l.observed_at = o.observed_at
                    AND l.model_version = o.model_version
                    AND l.evaluation_version = ?
                    AND l.horizon_minutes = ?
              )
            ORDER BY o.observed_at ASC
            LIMIT ?
            """,
            (MODEL_VERSION, eligible_before, EVALUATION_VERSION, int(horizon_minutes), max(1, int(limit))),
        ).fetchall()
    return tuple(
        SpringForwardLabelSeedV1(
            instrument_id=int(row["instrument_id"]),
            observed_at=row["observed_at"],
            close_price=float(row["close_price"]),
        )
        for row in rows
    )


def load_spring_observations_v1(
    *,
    instrument_id: int,
    start: datetime,
    end: datetime,
    limit: int = 5000,
) -> tuple[SpringObservationV1, ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT instrument_id, market_id, market_name, observed_at,
                   source_window_minutes, bar_count, close_price, equilibrium_price,
                   displacement_pct, velocity_pct_per_min, acceleration_pct_per_min2,
                   realized_volatility_pct, range_volatility_pct, shock_score,
                   energy_proxy, turning_state, estimated_period_minutes, damping_ratio,
                   oscillation_confidence, context_equilibrium_price, data_quality
            FROM pg_v2_spring_observations
            WHERE instrument_id = ? AND model_version = ?
              AND observed_at >= ? AND observed_at <= ?
            ORDER BY observed_at ASC
            LIMIT ?
            """,
            (int(instrument_id), MODEL_VERSION, start, end, max(1, int(limit))),
        ).fetchall()
    return tuple(
        SpringObservationV1(
            instrument_id=int(row["instrument_id"]),
            market_id=int(row["market_id"]),
            market_name=str(row["market_name"]),
            observed_at=row["observed_at"],
            source_window_minutes=int(row["source_window_minutes"]),
            bar_count=int(row["bar_count"]),
            close_price=float(row["close_price"]),
            equilibrium_price=float(row["equilibrium_price"]),
            displacement_pct=float(row["displacement_pct"]),
            velocity_pct_per_min=float(row["velocity_pct_per_min"]),
            acceleration_pct_per_min2=float(row["acceleration_pct_per_min2"]),
            realized_volatility_pct=float(row["realized_volatility_pct"]),
            range_volatility_pct=float(row["range_volatility_pct"]),
            shock_score=float(row["shock_score"]),
            energy_proxy=float(row["energy_proxy"]),
            turning_state=str(row["turning_state"]),
            estimated_period_minutes=None if row["estimated_period_minutes"] is None else float(row["estimated_period_minutes"]),
            damping_ratio=None if row["damping_ratio"] is None else float(row["damping_ratio"]),
            oscillation_confidence=None if row["oscillation_confidence"] is None else float(row["oscillation_confidence"]),
            context_equilibrium_price=None if row["context_equilibrium_price"] is None else float(row["context_equilibrium_price"]),
            data_quality=str(row["data_quality"]),
        )
        for row in rows
    )


__all__ = [
    "EVALUATION_VERSION",
    "SpringForwardLabelSeedV1",
    "ensure_spring_evaluation_schema_v1",
    "load_pending_forward_label_seeds_v1",
    "load_spring_observations_v1",
    "persist_episode_candidate_v1",
    "persist_forward_label_v1",
    "persist_runtime_coverage_v1",
    "persist_turning_point_v1",
]
