from __future__ import annotations

from dataclasses import dataclass

from autotrader_managed_positions_v1 import enroll_position_v1, is_position_managed_v1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
)
from database import connect, using_postgres
from saxo_provider import configured_client


REQUEST_SUPERSEDED = "SUPERSEDED"
UNSTARTED_REQUEST_STATUSES = ("PENDING", "APPROVED")
INFLIGHT_EXECUTION_STATUSES = ("SUBMITTING", "ORDER_ACCEPTED", "UNCERTAIN")


@dataclass(frozen=True, slots=True)
class ManualEntryAdoptionCycleV2:
    candidates: int
    adopted: int
    unchanged: int
    failed: int


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


def _pg_execution_inflight_v2(enrollment: StrategyEnrollmentV2) -> bool:
    """Block basis rotation while any PriceGauger order may still change it."""
    with connect() as db:
        request = db.execute(
            """
            SELECT request_id
            FROM pg_v2_autotrader_execution_requests
            WHERE action IN ('OPEN', 'CLOSE')
              AND account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
        if request is not None:
            return True
        open_attempt = db.execute(
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
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
        if open_attempt is not None:
            return True
        close_attempt = db.execute(
            """
            SELECT event_id
            FROM pg_v2_autotrader_live_close_attempts
            WHERE account_id = ? AND uic = ? AND asset_type = ?
              AND status IN (?, ?, ?)
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                *INFLIGHT_EXECUTION_STATUSES,
            ),
        ).fetchone()
    return close_attempt is not None


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
    the next adoption cycle can safely retry. This includes a same-net-position resize:
    exact basis, not Saxo's reusable id, defines managed authority.
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
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
            ),
        )


def adopt_manual_entry_position_v2(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2,
) -> bool:
    """Adopt a user-created exact Saxo position into a persistent Manage-only pilot.

    This function grants *no* OPEN authority. It only rotates the exact managed
    position basis after the user has independently created/resized/reversed exposure
    in Saxo. Existing managed-position enrollment owns the risk-epoch reset and the
    hardened strategy/risk CLOSE paths continue unchanged.

    Returns True only when a new/changed basis was adopted. An already exact managed
    basis is a no-op apart from repairing a stale strategy anchor if necessary.
    """
    ensure_autotrader_schema_v2()
    _require_manual_manage_identity_v2(enrollment, observation)

    if is_position_managed_v1(observation):
        _repair_anchor_if_needed_v2(enrollment, observation)
        return False

    if _pg_execution_inflight_v2(enrollment):
        raise RuntimeError("manual position adoption blocked while PriceGauger execution is unresolved")

    _retire_prior_manual_basis_v2(enrollment, observation)
    # #237 makes this the risk-management epoch boundary: existing observer-only
    # high-water/trigger state is reset before exact managed authority is granted.
    enroll_position_v1(observation)
    _repair_anchor_if_needed_v2(enrollment, observation)
    return True


def _exact_product_observation_v2(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple Saxo positions match one Manage-only product")
    return matches[0] if matches else None


def run_manual_entry_adoption_cycle_v2() -> ManualEntryAdoptionCycleV2:
    """Continuously rotate manual Saxo exposure into exact managed CLOSE authority.

    The cycle is intentionally useful only for MANUAL_ENTRY_ONLY. It cannot create
    exposure and it does not run when there are no active Manage-only pilots.
    """
    if not using_postgres():
        return ManualEntryAdoptionCycleV2(0, 0, 0, 0)
    ensure_autotrader_schema_v2()
    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.enabled
        and item.execution_mode == EXECUTION_MODE_LIVE
        and item.entry_mode == ENTRY_MODE_MANUAL_ONLY
    )
    if not enrollments:
        return ManualEntryAdoptionCycleV2(0, 0, 0, 0)

    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    observations = _position_observations_v2(client)

    candidates = 0
    adopted = 0
    unchanged = 0
    failed = 0
    for enrollment in enrollments:
        try:
            observation = _exact_product_observation_v2(enrollment, observations)
            if observation is None:
                continue
            candidates += 1
            if adopt_manual_entry_position_v2(enrollment, observation):
                adopted += 1
            else:
                unchanged += 1
        except Exception:
            # The surrounding daemon logs/continues; one ambiguous or in-flight
            # product must not prevent other independent Manage-only pilots.
            failed += 1
    return ManualEntryAdoptionCycleV2(candidates, adopted, unchanged, failed)


__all__ = [
    "INFLIGHT_EXECUTION_STATUSES",
    "ManualEntryAdoptionCycleV2",
    "UNSTARTED_REQUEST_STATUSES",
    "adopt_manual_entry_position_v2",
    "run_manual_entry_adoption_cycle_v2",
]
