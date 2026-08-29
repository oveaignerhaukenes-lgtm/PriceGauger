from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autotrader_live_pilot_runtime_v2 import LivePilotBindingV2, resolve_live_pilot_binding_v2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_managed_positions_v1 import enroll_position_v1, stop_managing_position_v1
from autotrader_pilot_equity_v2 import (
    DEFAULT_PILOT_SEED_CAPITAL,
    PilotEquitySnapshotV2,
    initialize_pilot_equity_v2,
)
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from database import connect


@dataclass(frozen=True, slots=True)
class StrategyEnrollmentV2:
    pilot_key: str
    strategy_key: str
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
    def binding(self) -> LivePilotBindingV2:
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
        "account_id": row[2],
        "anchor_net_position_id": row[3],
        "uic": row[4],
        "asset_type": row[5],
        "market_id": row[6],
        "instrument_id": row[7],
        "market_name": row[8],
        "enabled": row[9],
        "live_open_armed": row[10],
    }
    return StrategyEnrollmentV2(
        pilot_key=str(values["pilot_key"]),
        strategy_key=str(values["strategy_key"]),
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


def enroll_macd_flip_position_v2(
    observation: PositionObservationV2,
    *,
    seed_capital: float = DEFAULT_PILOT_SEED_CAPITAL,
    currency: str = "NOK",
) -> tuple[StrategyEnrollmentV2, PilotEquitySnapshotV2]:
    """Explicitly attach the only current strategy to one exact live position.

    Enrollment also opts the exact current basis into the existing risk-managed
    position boundary. LIVE OPEN remains separately disarmed until the user arms it.
    """
    ensure_autotrader_schema_v2()
    binding = resolve_live_pilot_binding_v2(
        account_id=observation.account_id,
        anchor_net_position_id=observation.net_position_id,
        uic=observation.uic,
        asset_type=observation.asset_type,
    )
    equity = initialize_pilot_equity_v2(
        pilot_key=binding.pilot_key,
        seed_capital=float(seed_capital),
        currency=currency,
    )
    enroll_position_v1(observation)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_strategy_enrollments(
                pilot_key, strategy_key, account_id, anchor_net_position_id,
                uic, asset_type, market_id, instrument_id, market_name,
                enabled, live_open_armed, enrolled_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, FALSE, now(), now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
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
                binding.pilot_key,
                MACD_FLIP_STRATEGY_V2,
                binding.account_id,
                binding.anchor_net_position_id,
                binding.uic,
                binding.asset_type,
                binding.market_id,
                binding.instrument_id,
                binding.market_name,
            ),
        )
    enrollment = load_strategy_enrollment_v2(binding.pilot_key)
    if enrollment is None:
        raise RuntimeError("strategy enrollment was not persisted")
    return enrollment, equity


def load_strategy_enrollment_v2(pilot_key: str) -> StrategyEnrollmentV2 | None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, strategy_key, account_id, anchor_net_position_id,
                   uic, asset_type, market_id, instrument_id, market_name,
                   enabled, live_open_armed
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    return _row_to_enrollment(row)


def load_active_strategy_enrollments_v2() -> tuple[StrategyEnrollmentV2, ...]:
    ensure_autotrader_schema_v2()
    with connect() as db:
        rows = db.execute(
            """
            SELECT pilot_key, strategy_key, account_id, anchor_net_position_id,
                   uic, asset_type, market_id, instrument_id, market_name,
                   enabled, live_open_armed
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE
            ORDER BY enrolled_at ASC
            """
        ).fetchall()
    return tuple(item for row in rows if (item := _row_to_enrollment(row)) is not None)


def find_strategy_enrollment_for_close_v2(
    *,
    account_id: str,
    net_position_id: str,
    uic: int,
    asset_type: str,
) -> StrategyEnrollmentV2 | None:
    """Match a close to the exact currently enrolled strategy position basis."""
    ensure_autotrader_schema_v2()
    with connect() as db:
        rows = db.execute(
            """
            SELECT pilot_key, strategy_key, account_id, anchor_net_position_id,
                   uic, asset_type, market_id, instrument_id, market_name,
                   enabled, live_open_armed
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE enabled = TRUE
              AND account_id = ?
              AND anchor_net_position_id = ?
              AND uic = ?
              AND asset_type = ?
            """,
            (str(account_id), str(net_position_id), int(uic), str(asset_type)),
        ).fetchall()
    matches = tuple(item for row in rows if (item := _row_to_enrollment(row)) is not None)
    if len(matches) > 1:
        raise RuntimeError("multiple active strategy enrollments matched one close attempt")
    return matches[0] if matches else None


def set_live_open_armed_v2(pilot_key: str, armed: bool) -> StrategyEnrollmentV2:
    ensure_autotrader_schema_v2()
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET live_open_armed = ?, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE
            """,
            (bool(armed), str(pilot_key)),
        )
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if enrollment is None or not enrollment.enabled:
        raise LookupError(f"no active strategy enrollment for {pilot_key}")
    return enrollment


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
    stop_managing_position_v1(enrollment.account_id, enrollment.anchor_net_position_id)


__all__ = [
    "StrategyEnrollmentV2",
    "enroll_macd_flip_position_v2",
    "find_strategy_enrollment_for_close_v2",
    "load_active_strategy_enrollments_v2",
    "load_strategy_enrollment_v2",
    "set_live_open_armed_v2",
    "stop_strategy_enrollment_v2",
]
