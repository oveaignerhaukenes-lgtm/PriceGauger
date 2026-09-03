from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Iterable

from autotrader_shadow_benchmark_v2 import ShadowBenchmarkSeriesV2, ShadowEquityPointV2
from database import connect


SERIES_SCHEMA_VERSION = 1
MATERIALIZER_VERSION = "strategy-series-bridge-v1"
VALID_DIRECTIONS = {"FLAT", "LONG", "SHORT"}


@dataclass(frozen=True, slots=True)
class StrategySeriesIdentityV1:
    series_key: str
    account_id: str
    uic: int
    asset_type: str
    instrument_id: int
    strategy_key: str
    strategy_version: str
    started_at: datetime
    currency: str
    seed_equity: float
    execution_mode: str


@dataclass(frozen=True, slots=True)
class StrategySeriesPointV1:
    observed_at: datetime
    position_state: str
    equity_1x: float
    return_pct_1x: float
    effective_leverage: float
    equity_pilot_equivalent: float
    return_pct_pilot_equivalent: float


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def strategy_series_key_v1(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    instrument_id: int,
    strategy_key: str,
    strategy_version: str,
    started_at: datetime,
) -> str:
    material = "|".join(
        (
            str(account_id),
            str(int(uic)),
            str(asset_type),
            str(int(instrument_id)),
            str(strategy_key),
            str(strategy_version),
            _utc(started_at).isoformat(),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def ensure_strategy_series_schema_v1() -> None:
    """Create the common model-series contract.

    AutoTrader has historically owned several bounded runtime tables outside the DB-v2
    foundation migration. This table is intentionally *shared* by every model: adding a
    new strategy must append rows here rather than invent another chart/equity schema.
    """
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_strategy_series_points (
                series_key TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                account_id TEXT NOT NULL,
                uic BIGINT NOT NULL,
                asset_type TEXT NOT NULL,
                instrument_id BIGINT NOT NULL,
                strategy_key TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                position_state TEXT NOT NULL CHECK (position_state IN ('FLAT','LONG','SHORT')),
                currency TEXT NOT NULL,
                seed_equity DOUBLE PRECISION NOT NULL,
                equity_1x DOUBLE PRECISION NOT NULL,
                return_pct_1x DOUBLE PRECISION NOT NULL,
                effective_leverage DOUBLE PRECISION NOT NULL,
                equity_pilot_equivalent DOUBLE PRECISION NOT NULL,
                return_pct_pilot_equivalent DOUBLE PRECISION NOT NULL,
                materializer_version TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (series_key, observed_at)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_strategy_series_instrument_time_idx
            ON pg_v2_strategy_series_points(instrument_id, observed_at DESC)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_strategy_series_strategy_time_idx
            ON pg_v2_strategy_series_points(strategy_key, strategy_version, observed_at DESC)
            """
        )


def make_strategy_series_identity_v1(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    instrument_id: int,
    strategy_key: str,
    strategy_version: str,
    started_at: datetime,
    currency: str,
    seed_equity: float,
    execution_mode: str,
) -> StrategySeriesIdentityV1:
    started = _utc(started_at)
    seed = float(seed_equity)
    if seed <= 0:
        raise ValueError("strategy series seed_equity must be positive")
    return StrategySeriesIdentityV1(
        series_key=strategy_series_key_v1(
            account_id=account_id,
            uic=uic,
            asset_type=asset_type,
            instrument_id=instrument_id,
            strategy_key=strategy_key,
            strategy_version=strategy_version,
            started_at=started,
        ),
        account_id=str(account_id),
        uic=int(uic),
        asset_type=str(asset_type),
        instrument_id=int(instrument_id),
        strategy_key=str(strategy_key),
        strategy_version=str(strategy_version),
        started_at=started,
        currency=str(currency),
        seed_equity=seed,
        execution_mode=str(execution_mode),
    )


def persist_strategy_series_points_v1(
    identity: StrategySeriesIdentityV1,
    points: Iterable[StrategySeriesPointV1],
) -> int:
    ensure_strategy_series_schema_v1()
    inserted = 0
    with connect() as db:
        for point in points:
            direction = str(point.position_state).upper()
            if direction not in VALID_DIRECTIONS:
                raise ValueError(f"unsupported strategy series position state: {direction}")
            before = getattr(db, "total_changes", None)
            cursor = db.execute(
                """
                INSERT INTO pg_v2_strategy_series_points(
                    series_key, schema_version, account_id, uic, asset_type,
                    instrument_id, strategy_key, strategy_version, execution_mode,
                    started_at, observed_at, position_state, currency, seed_equity,
                    equity_1x, return_pct_1x, effective_leverage,
                    equity_pilot_equivalent, return_pct_pilot_equivalent,
                    materializer_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (series_key, observed_at) DO NOTHING
                """,
                (
                    identity.series_key,
                    SERIES_SCHEMA_VERSION,
                    identity.account_id,
                    identity.uic,
                    identity.asset_type,
                    identity.instrument_id,
                    identity.strategy_key,
                    identity.strategy_version,
                    identity.execution_mode,
                    identity.started_at,
                    _utc(point.observed_at),
                    direction,
                    identity.currency,
                    identity.seed_equity,
                    float(point.equity_1x),
                    float(point.return_pct_1x),
                    float(point.effective_leverage),
                    float(point.equity_pilot_equivalent),
                    float(point.return_pct_pilot_equivalent),
                    MATERIALIZER_VERSION,
                ),
            )
            rowcount = getattr(cursor, "rowcount", None)
            if rowcount is not None and int(rowcount) > 0:
                inserted += 1
            elif before is not None and getattr(db, "total_changes", before) > before:
                inserted += 1
    return inserted


def load_persisted_strategy_series_v1(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    instrument_id: int,
    pilot_equivalent: bool = True,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Read the latest versioned series per strategy for one exact product.

    Consumers never need to know which producer created a point. That is the key
    compatibility contract for the Strategy Lab chart and later offline learning.
    """
    ensure_strategy_series_schema_v1()
    with connect() as db:
        identities = db.execute(
            """
            SELECT series_key, strategy_key, strategy_version, execution_mode,
                   currency, seed_equity, started_at, MAX(observed_at) AS latest_at
            FROM pg_v2_strategy_series_points
            WHERE account_id = ? AND uic = ? AND asset_type = ? AND instrument_id = ?
            GROUP BY series_key, strategy_key, strategy_version, execution_mode,
                     currency, seed_equity, started_at
            ORDER BY strategy_key ASC, latest_at DESC
            """,
            (str(account_id), int(uic), str(asset_type), int(instrument_id)),
        ).fetchall()
    # Keep only the newest cohort/version of each strategy key. Historical rows remain
    # immutable and queryable for research; the live chart should not duplicate labels.
    chosen: dict[str, dict[str, Any]] = {}
    for row in identities:
        values = dict(row) if isinstance(row, dict) else {
            "series_key": row[0], "strategy_key": row[1], "strategy_version": row[2],
            "execution_mode": row[3], "currency": row[4], "seed_equity": row[5],
            "started_at": row[6], "latest_at": row[7],
        }
        key = str(values["strategy_key"])
        candidate = dict(values)
        existing = chosen.get(key)
        if existing is None or _utc(candidate["latest_at"]) > _utc(existing["latest_at"]):
            chosen[key] = candidate

    series: list[ShadowBenchmarkSeriesV2] = []
    with connect() as db:
        for strategy_key in sorted(chosen):
            identity = chosen[strategy_key]
            rows = db.execute(
                """
                SELECT observed_at, position_state, equity_1x, equity_pilot_equivalent
                FROM pg_v2_strategy_series_points
                WHERE series_key = ?
                ORDER BY observed_at ASC
                """,
                (str(identity["series_key"]),),
            ).fetchall()
            points: list[ShadowEquityPointV2] = []
            for row in rows:
                values = dict(row) if isinstance(row, dict) else {
                    "observed_at": row[0], "position_state": row[1],
                    "equity_1x": row[2], "equity_pilot_equivalent": row[3],
                }
                equity = (
                    float(values["equity_pilot_equivalent"])
                    if pilot_equivalent
                    else float(values["equity_1x"])
                )
                points.append(
                    ShadowEquityPointV2(
                        closed_at=_utc(values["observed_at"]),
                        equity=equity,
                        position_state=str(values["position_state"]),
                    )
                )
            series.append(
                ShadowBenchmarkSeriesV2(
                    strategy_key=str(identity["strategy_key"]),
                    execution_mode=str(identity["execution_mode"]),
                    currency=str(identity["currency"]),
                    seed_equity=float(identity["seed_equity"]),
                    started_at=_utc(identity["started_at"]),
                    points=tuple(points),
                )
            )
    return tuple(series)


__all__ = [
    "MATERIALIZER_VERSION",
    "SERIES_SCHEMA_VERSION",
    "StrategySeriesIdentityV1",
    "StrategySeriesPointV1",
    "ensure_strategy_series_schema_v1",
    "load_persisted_strategy_series_v1",
    "make_strategy_series_identity_v1",
    "persist_strategy_series_points_v1",
    "strategy_series_key_v1",
]
