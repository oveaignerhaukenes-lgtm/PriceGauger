from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autotrader_automanage_container_v2 import AutoManageProductV2, resolve_saxo_automanage_product_v2
from autotrader_live_pilot_runtime_v2 import LivePilotBindingV2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_managed_positions_v1 import enroll_position_v1, stop_managing_position_v1
from autotrader_pilot_equity_v2 import (
    DEFAULT_PILOT_SEED_CAPITAL,
    PilotEquitySnapshotV2,
    initialize_pilot_equity_v2,
)
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import strategy_spec_v2
from database import connect


EXECUTION_MODE_LIVE = "LIVE_MANAGE"
EXECUTION_MODE_SHADOW = "SHADOW"
_EXECUTION_MODES = {EXECUTION_MODE_LIVE, EXECUTION_MODE_SHADOW}


@dataclass(frozen=True, slots=True)
class StrategyEnrollmentV2:
    pilot_key: str
    strategy_key: str
    execution_mode: str
    account_id: str
    anchor_net_position_id: str
    uic: int
    asset_type: str
    market_id: int
    instrument_id: int
    market_name: str
    enabled: bool
    live_open_armed: bool

    @property
    def product(self) -> AutoManageProductV2:
        return AutoManageProductV2(
            provider="saxo",
            account_id=self.account_id,
            anchor_position_id=self.anchor_net_position_id,
            provider_instrument_id=str(self.uic),
            asset_type=self.asset_type,
            market_id=self.market_id,
            market_name=self.market_name,
            instrument_id=self.instrument_id,
        )

    @property
    def binding(self) -> LivePilotBindingV2:
        """Compatibility binding for the existing flip runtime adapter."""
        return LivePilotBindingV2(
            account_id=self.account_id,
            anchor_net_position_id=self.anchor_net_position_id,
            uic=self.uic,
            asset_type=self.asset_type,
            market_id=self.market_id,
            market_name=self.market_name,
            instrument_id=self.instrument_id,
        )


def _row_to_enrollment(row: Any) -> StrategyEnrollmentV2 | None:
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "pilot_key": row[0],
        "strategy_key": row[1],
        "execution_mode": row[2],
        "account_id": row[3],
        "anchor_net_position_id": row[4],
        "uic": row[5],
        "asset_type": row[6],
        "market_id": row[7],
        "instrument_id": row[8],
        "market_name": row[9],
        "enabled": row[10],
        "live_open_armed": row[11],
    }
    return StrategyEnrollmentV2(
        pilot_key=str(values["pilot_key"]),
        strategy_key=str(values["strategy_key"]),
        execution_mode=str(values["execution_mode"]),
        account_id=str(values["account_id"]),
        anchor_net_position_id=str(values["anchor_net_position_id"]),
        uic=int(values["uic"]),
        asset_type=str(values["asset_type"]),
        market_id=int(values["market_id"]),
        instrument_id=int(values["instrument_id"]),
        market_name=str(values["market_name"]),
        enabled=bool(values["enabled"]),
        live_open_armed=bool(values["live_open_armed"]),
    )


def _select_columns() -> str:
    return (
        "pilot_key, strategy_key, execution_mode, account_id, anchor_net_position_id, "
        "uic, asset_type, market_id, instrument_id, market_name, enabled, live_open_armed"
    )


def enroll_strategy_position_v2(
    observation: PositionObservationV2,
    *,
    strategy_key: str,
    execution_mode: str = EXECUTION_MODE_LIVE,
    seed_capital: float = DEFAULT_PILOT_SEED_CAPITAL,
    currency: str = "NOK",
) -> tuple[StrategyEnrollmentV2, PilotEquitySnapshotV2]:
    """Attach any supported strategy to any exact subscribed Saxo product.

    The product container is strategy-neutral. Several strategies may be enrolled
    against one product in SHADOW mode for comparison, while a PostgreSQL partial
    unique index permits at most one enabled LIVE_MANAGE strategy per exact product.
    """
    ensure_autotrader_schema_v2()
    strategy_spec_v2(strategy_key)
    mode = str(execution_mode or "").strip().upper()
    if mode not in _EXECUTION_MODES:
        raise ValueError(f"unsupported execution_mode: {execution_mode}")

    product = resolve_saxo_automanage_product_v2(observation)
    pilot_key = product.pilot_key(strategy_key)
    equity = initialize_pilot_equity_v2(
        pilot_key=pilot_key,
        seed_capital=float(seed_capital),
        currency=currency,
    )

    if mode == EXECUTION_MODE_LIVE:
        enroll_position_v1(observation)

    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_enrollments(
                pilot_key, strategy_key, execution_mode, account_id, anchor_net_position_id,
                uic, asset_type, market_id, instrument_id, market_name,
                enabled, live_open_armed, enrolled_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, FALSE, now(), now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                execution_mode=EXCLUDED.execution_mode,
                account_id=EXCLUDED.account_id,
                anchor_net_position_id=EXCLUDED.anchor_net_position_id,
                uic=EXCLUDED.uic,
                asset_type=EXCLUDED.asset_type,
                market_id=EXCLUDED.market_id,
                instrument_id=EXCLUDED.instrument_id,
                market_name=EXCLUDED.market_name,
                enabled=TRUE,
                live_open_armed=FALSE,
                enrolled_at=now(),
                updated_at=now()
            """,
            (
                pilot_key,
                str(strategy_key),
                mode,
                product.account_id,
                product.anchor_position_id,
                int(product.provider_instrument_id),
                product.asset_type,
                product.market_id,
                product.instrument_id,
                product.market_name,
            ),
        )
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if enrollment is None:
        raise RuntimeError("strategy enrollment was not persisted")
    return enrollment, equity


def enroll_macd_flip_position_v2(
    observation: PositionObservationV2,
    *,
    seed_capital: float = DEFAULT_PILOT_SEED_CAPITAL,
    currency: str = "NOK",
) -> tuple[StrategyEnrollmentV2, PilotEquitySnapshotV2]:
    """Backward-compatible first-pilot wrapper."""
    return enroll_strategy_position_v2(
        observation,
        strategy_key=MACD_FLIP_STRATEGY_V2,
        execution_mode=EXECUTION_MODE_LIVE,
        seed_capital=seed_capital,
        currency=currency,
    )


def load_strategy_enrollment_v2(pilot_key: str) -> StrategyEnrollmentV2 | None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        row = db.execute(
            f"SELECT {_select_columns()} FROM pg_v2_autotrader_strategy_enrollments WHERE pilot_key = ?",
            (str(pilot_key),),
        ).fetchone()
    return _row_to_enrollment(row)


def load_active_strategy_enrollments_v2() -> tuple[StrategyEnrollmentV2, ...]:
    ensure_autotrader_schema_v2()
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT {_select_columns()}
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE
            ORDER BY enrolled_at ASC
            """
        ).fetchall()
    return tuple(item for row in rows if (item := _row_to_enrollment(row)) is not None)


def load_product_strategy_enrollments_v2(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
) -> tuple[StrategyEnrollmentV2, ...]:
    ensure_autotrader_schema_v2()
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT {_select_columns()}
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE AND account_id = ? AND uic = ? AND asset_type = ?
            ORDER BY execution_mode ASC, strategy_key ASC
            """,
            (str(account_id), int(uic), str(asset_type)),
        ).fetchall()
    return tuple(item for row in rows if (item := _row_to_enrollment(row)) is not None)


def find_strategy_enrollment_for_close_v2(
    *,
    account_id: str,
    net_position_id: str,
    uic: int,
    asset_type: str,
) -> StrategyEnrollmentV2 | None:
    """Match a real close only to the one LIVE strategy controlling this product.

    `net_position_id` is intentionally not the durable strategy identity: Saxo can
    issue a new net-position id after a later re-entry. Exact account + UIC +
    AssetType plus the one-live-controller invariant is the durable join.
    """
    del net_position_id
    ensure_autotrader_schema_v2()
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT {_select_columns()}
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE
              AND execution_mode = ?
              AND account_id = ?
              AND uic = ?
              AND asset_type = ?
            """,
            (EXECUTION_MODE_LIVE, str(account_id), int(uic), str(asset_type)),
        ).fetchall()
    matches = tuple(item for row in rows if (item := _row_to_enrollment(row)) is not None)
    if len(matches) > 1:
        raise RuntimeError("multiple LIVE strategy enrollments matched one product; invariant violated")
    return matches[0] if matches else None


def set_live_open_armed_v2(pilot_key: str, armed: bool) -> StrategyEnrollmentV2:
    ensure_autotrader_schema_v2()
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if enrollment is None or not enrollment.enabled:
        raise LookupError(f"no active strategy enrollment for {pilot_key}")
    if enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("LIVE OPEN cannot be armed for a SHADOW strategy")
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET live_open_armed = ?, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE AND execution_mode = ?
            """,
            (bool(armed), str(pilot_key), EXECUTION_MODE_LIVE),
        )
    refreshed = load_strategy_enrollment_v2(pilot_key)
    if refreshed is None:
        raise RuntimeError("strategy enrollment disappeared after arming update")
    return refreshed


def stop_strategy_enrollment_v2(pilot_key: str) -> None:
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if enrollment is None:
        return
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET enabled = FALSE, live_open_armed = FALSE, updated_at = now()
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        )
    if enrollment.execution_mode == EXECUTION_MODE_LIVE:
        stop_managing_position_v1(enrollment.account_id, enrollment.anchor_net_position_id)


__all__ = [
    "EXECUTION_MODE_LIVE",
    "EXECUTION_MODE_SHADOW",
    "StrategyEnrollmentV2",
    "enroll_macd_flip_position_v2",
    "enroll_strategy_position_v2",
    "find_strategy_enrollment_for_close_v2",
    "load_active_strategy_enrollments_v2",
    "load_product_strategy_enrollments_v2",
    "load_strategy_enrollment_v2",
    "set_live_open_armed_v2",
    "stop_strategy_enrollment_v2",
]
