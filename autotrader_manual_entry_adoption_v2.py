from __future__ import annotations

from typing import Any

from autotrader_managed_positions_v1 import enroll_position_v1, is_position_managed_v1
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
)
from database import connect


REQUEST_SUPERSEDED = "SUPERSEDED"
UNSTARTED_REQUEST_STATUSES = ("PENDING", "APPROVED")
INFLIGHT_OPEN_STATUSES = ("SUBMITTING", "ORDER_ACCEPTED", "UNCERTAIN")


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (TypeError, IndexError, KeyError):
        return row[index]


def _require_manual_manage_identity_v2(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2,
) -> None:
    if not enrollment.enabled or enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("manual position adoption requires an active LIVE_MANAGE enrollment")
    if enrollment.entry_mode != ENTRY_MODE_MANUAL_ONLY:
        raise ValueError("manual position adoption is only allowed in MANUAL_ENTRY_ONLY mode")
    if observation.account_id != enrollment.account_id:
        raise ValueError("manual position account does not match AutoManage enrollment")
    if int(observation.uic) != int(enrollment.uic):
        raise ValueError("manual position UIC does not match AutoManage enrollment")
    if observation.asset_type != enrollment.asset_type:
        raise ValueError("manual position AssetType does not match AutoManage enrollment")
    if not observation.net_position_id:
        raise ValueError("manual position requires a Saxo net-position identity")
    if float(observation.amount) <= 0 or float(observation.average_open_price) <= 0:
        raise ValueError("manual position basis must be positive")


def _pg_open_inflight_v2(enrollment: StrategyEnrollmentV2) -> bool:
    """Block manual adoption while PG may own an unresolved OPEN transition."""
    with connect() as db:
        request = db.execute(
            """
            SELECT request_id
            FROM pg_v2_autotrader_execution_requests
            WHERE action = 'OPEN'
              AND account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_OPEN_STATUSES,
            ),
        ).fetchone()
        if request is not None:
            return True
        attempt = db.execute(
            """
            SELECT request_id
            FROM pg_v2_autotrader_live_open_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_OPEN_STATUSES,
            ),
        ).fetchone()
    return attempt is not None


def _repair_anchor_if_needed_v2(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2,
) -> bool:
    if enrollment.anchor_net_position_id == observation.net_position_id:
        return False
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET anchor_net_position_id = ?, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE
              AND execution_mode = ? AND entry_mode = ?
            """,
            (
                observation.net_position_id,
                enrollment.pilot_key,
                EXECUTION_MODE_LIVE,
                ENTRY_MODE_MANUAL_ONLY,
            ),
        )
    return True


def _retire_prior_manual_basis_v2(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2,
) -> None:
    """Clear stale strategy authority before adopting the user's new basis.

    The transaction deliberately removes authority first. If the process dies before
    `enroll_position_v1`, the system is left fail-closed with no managed position;
    the next strategy cycle can safely retry adoption.
    """
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = ?, block_reason = 'MANUAL_POSITION_ADOPTED', updated_at = now()
            WHERE pilot_key = ? AND status IN (?, ?)
            """,
            (
                REQUEST_SUPERSEDED,
                enrollment.pilot_key,
                *UNSTARTED_REQUEST_STATUSES,
            ),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_runtime_state
            SET pending_intent_id = NULL,
                pending_signal_at = NULL,
                pending_signal = NULL,
                pending_target_direction = NULL,
                pending_previous_macd = NULL,
                pending_previous_signal = NULL,
                pending_current_macd = NULL,
                pending_current_signal = NULL,
                pending_budget_amount = NULL,
                pending_budget_currency = NULL,
                updated_at = now()
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_managed_positions
            SET managed = FALSE, updated_at = now()
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND NOT (net_position_id = ?)
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                observation.net_position_id,
            ),
        )


def adopt_manual_entry_position_v2(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2,
) -> bool:
    """Adopt a user-created exact Saxo position into a persistent Manage-only pilot.

    This function grants *no* OPEN authority. It only rotates the exact managed
    position basis after the user has independently created/resized/reversed exposure
    in Saxo. The existing managed-position enrollment then owns risk-epoch reset and
    the hardened strategy/risk CLOSE paths continue unchanged.

    Returns True only when a new/changed basis was adopted. An already exact managed
    basis is a no-op apart from repairing a stale strategy anchor if necessary.
    """
    ensure_autotrader_schema_v2()
    _require_manual_manage_identity_v2(enrollment, observation)

    if is_position_managed_v1(observation):
        _repair_anchor_if_needed_v2(enrollment, observation)
        return False

    if _pg_open_inflight_v2(enrollment):
        raise RuntimeError("manual position adoption blocked while PriceGauger OPEN is unresolved")

    _retire_prior_manual_basis_v2(enrollment, observation)
    # #237 makes this the risk-management epoch boundary: existing observer-only
    # high-water/trigger state is reset before exact managed authority is granted.
    enroll_position_v1(observation)
    _repair_anchor_if_needed_v2(enrollment, observation)
    return True


__all__ = [
    "INFLIGHT_OPEN_STATUSES",
    "UNSTARTED_REQUEST_STATUSES",
    "adopt_manual_entry_position_v2",
]
