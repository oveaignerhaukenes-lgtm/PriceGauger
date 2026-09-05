from __future__ import annotations

from database import connect
from spring_trade_engine import SPRING_ENGINE_SCHEMA_VERSION
from spring_trade_engine.contracts import SpringObservationV1


MODEL_VERSION = "spring-observer-primitives-v1"


def ensure_spring_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_spring_observations (
                instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                observed_at TIMESTAMPTZ NOT NULL,
                schema_version INTEGER NOT NULL,
                model_version TEXT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                market_name TEXT NOT NULL,
                source_window_minutes INTEGER NOT NULL,
                bar_count INTEGER NOT NULL,
                close_price DOUBLE PRECISION NOT NULL,
                equilibrium_price DOUBLE PRECISION NOT NULL,
                displacement_pct DOUBLE PRECISION NOT NULL,
                velocity_pct_per_min DOUBLE PRECISION NOT NULL,
                acceleration_pct_per_min2 DOUBLE PRECISION NOT NULL,
                realized_volatility_pct DOUBLE PRECISION NOT NULL,
                range_volatility_pct DOUBLE PRECISION NOT NULL,
                shock_score DOUBLE PRECISION NOT NULL,
                energy_proxy DOUBLE PRECISION NOT NULL,
                turning_state TEXT NOT NULL,
                estimated_period_minutes DOUBLE PRECISION,
                damping_ratio DOUBLE PRECISION,
                oscillation_confidence DOUBLE PRECISION,
                context_equilibrium_price DOUBLE PRECISION,
                data_quality TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (instrument_id, observed_at, model_version)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_spring_observations_market_time_idx
            ON pg_v2_spring_observations(market_id, observed_at DESC)
            """
        )


def persist_spring_observation_v1(observation: SpringObservationV1) -> None:
    ensure_spring_schema_v1()
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_spring_observations(
                instrument_id, observed_at, schema_version, model_version,
                market_id, market_name, source_window_minutes, bar_count,
                close_price, equilibrium_price, displacement_pct,
                velocity_pct_per_min, acceleration_pct_per_min2,
                realized_volatility_pct, range_volatility_pct,
                shock_score, energy_proxy, turning_state,
                estimated_period_minutes, damping_ratio, oscillation_confidence,
                context_equilibrium_price, data_quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (instrument_id, observed_at, model_version) DO NOTHING
            """,
            (
                observation.instrument_id,
                observation.observed_at,
                SPRING_ENGINE_SCHEMA_VERSION,
                MODEL_VERSION,
                observation.market_id,
                observation.market_name,
                observation.source_window_minutes,
                observation.bar_count,
                observation.close_price,
                observation.equilibrium_price,
                observation.displacement_pct,
                observation.velocity_pct_per_min,
                observation.acceleration_pct_per_min2,
                observation.realized_volatility_pct,
                observation.range_volatility_pct,
                observation.shock_score,
                observation.energy_proxy,
                observation.turning_state,
                observation.estimated_period_minutes,
                observation.damping_ratio,
                observation.oscillation_confidence,
                observation.context_equilibrium_price,
                observation.data_quality,
            ),
        )


__all__ = ["MODEL_VERSION", "ensure_spring_schema_v1", "persist_spring_observation_v1"]
