from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    FastLiveStateV2,
    _observed_direction,
    _persist_intent_and_request_v2,
)
from autotrader_manage_control_v1 import auto_manage_enabled_v1, set_auto_manage_enabled_v1
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_entry_adoption_v2 import adopt_user_confirmed_position_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strategy_switch_v2 import _pg_execution_inflight_v2
from database import connect

MODE_RUNNING = "RUNNING"
MODE_PAUSING = "PAUSING"
MODE_PAUSED = "PAUSED"
MODE_STOPPED = "STOPPED"
MODE_STOPPING_CLOSE = "STOPPING_CLOSE"
VALID_MODES = {MODE_RUNNING, MODE_PAUSING, MODE_PAUSED, MODE_STOPPED, MODE_STOPPING_CLOSE}


@dataclass(frozen=True, slots=True)
class OperatorControlV1:
    pilot_key: str
    mode: str
    requested_at: datetime
    reason: str


def ensure_operator_control_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_operator_control (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                mode TEXT NOT NULL CHECK (mode IN ('RUNNING','PAUSING','PAUSED','STOPPED','STOPPING_CLOSE')),
                reason TEXT NOT NULL DEFAULT '',
                requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _utc(value) -> datetime:
    item = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if item.tzinfo is None:
        item = item.replace(tzinfo=timezone.utc)
    return item.astimezone(timezone.utc)


def _save(enrollment: StrategyEnrollmentV2, mode: str, *, reason: str) -> OperatorControlV1:
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported operator mode: {mode}")
    now = datetime.now(timezone.utc)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_operator_control(
                pilot_key, mode, reason, requested_at, updated_at
            ) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                mode=EXCLUDED.mode, reason=EXCLUDED.reason,
                requested_at=EXCLUDED.requested_at, updated_at=now()
            """,
            (enrollment.pilot_key, mode, str(reason), now),
        )
    return OperatorControlV1(enrollment.pilot_key, mode, now, str(reason))


def load_operator_control_v1(enrollment: StrategyEnrollmentV2) -> OperatorControlV1:
    ensure_operator_control_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, mode, requested_at, reason
            FROM pg_v2_autotrader_operator_control WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
    if row is None:
        mode = MODE_RUNNING if auto_manage_enabled_v1(enrollment) else MODE_STOPPED
        return OperatorControlV1(enrollment.pilot_key, mode, datetime.now(timezone.utc), "DERIVED")
    item = dict(row) if isinstance(row, dict) else {
        "pilot_key": row[0], "mode": row[1], "requested_at": row[2], "reason": row[3]
    }
    return OperatorControlV1(
        pilot_key=str(item["pilot_key"]), mode=str(item["mode"]),
        requested_at=_utc(item["requested_at"]), reason=str(item["reason"] or ""),
    )


def effective_operator_control_v1(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2 | None,
) -> OperatorControlV1:
    """Collapse transitional close modes after exact Saxo FLAT is observed.

    This write is idempotent and only updates operator-control metadata. It does not
    infer P/L settlement or create execution authority.
    """
    state = load_operator_control_v1(enrollment)
    if observation is not None:
        return state
    if state.mode == MODE_PAUSING:
        return _save(enrollment, MODE_PAUSED, reason="EXACT_SAXO_FLAT_AFTER_PAUSE")
    if state.mode == MODE_STOPPING_CLOSE:
        return _save(enrollment, MODE_STOPPED, reason="EXACT_SAXO_FLAT_AFTER_CLOSE_STOP")
    return state


def _require_live(enrollment: StrategyEnrollmentV2) -> None:
    if not enrollment.enabled or enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("operator control requires an active LIVE AutoManager controller")


def _active_anomaly_exists(enrollment: StrategyEnrollmentV2) -> bool:
    try:
        with connect() as db:
            row = db.execute(
                """
                SELECT 1 FROM pg_v2_autotrader_execution_anomalies
                WHERE active = TRUE AND account_id = ? AND uic = ? AND asset_type = ?
                  AND severity IN ('HIGH','CRITICAL')
                LIMIT 1
                """,
                (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
            ).fetchone()
    except Exception:
        return False
    return row is not None


def _request_flat_v1(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2 | None,
    *,
    transitional_mode: str,
    final_mode: str,
    signal: str,
) -> OperatorControlV1:
    _require_live(enrollment)

    # Remove future strategy OPEN/CLOSE authority first. The dedicated operator CLOSE
    # is persisted afterwards and remains consumable by the existing close executor,
    # which does not require auto_manage_enabled=TRUE.
    set_auto_manage_enabled_v1(enrollment, False)

    if observation is None:
        return _save(enrollment, final_mode, reason=f"{signal}:ALREADY_FLAT")

    if not is_position_managed_v1(observation):
        # Button press is an explicit user operation, so exact-basis takeover is
        # permitted here. Background adoption remains guarded by #322.
        adopt_user_confirmed_position_v2(enrollment, observation)

    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("vent til pågående PriceGauger/Saxo-ordre er avklart")

    now = datetime.now(timezone.utc)
    state = FastLiveStateV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=DIRECTION_FLAT,
        last_action_at=now,
        pending_target_direction=DIRECTION_FLAT,
        intent_event_id=str(uuid4()),
        intent_signal_at=now,
        intent_signal=signal,
    )
    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    created = _persist_intent_and_request_v2(
        enrollment=enrollment,
        state=state,
        observed=observation,
        observed_direction=_observed_direction(observation),
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
        supersede_prior=True,
    )
    if not created:
        raise RuntimeError("operator FLAT target did not create a CLOSE request")
    return _save(enrollment, transitional_mode, reason=signal)


def pause_automanager_v1(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2 | None,
) -> OperatorControlV1:
    """Go FLAT through the normal CLOSE lifecycle, then remain paused."""
    return _request_flat_v1(
        enrollment, observation,
        transitional_mode=MODE_PAUSING,
        final_mode=MODE_PAUSED,
        signal="USER_OPERATOR_PAUSE_FLAT",
    )


def start_automanager_v1(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2 | None,
) -> OperatorControlV1:
    """Resume the same controller/strategy without synthesizing a new market target."""
    _require_live(enrollment)
    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("vent til pågående PriceGauger/Saxo-ordre er avklart")
    if _active_anomaly_exists(enrollment):
        raise ValueError("execution guard har en uavklart hendelse; AutoManager startes ikke")
    if observation is not None and not is_position_managed_v1(observation):
        adopt_user_confirmed_position_v2(enrollment, observation)
    set_auto_manage_enabled_v1(enrollment, True)
    return _save(enrollment, MODE_RUNNING, reason="USER_OPERATOR_START")


def stop_automanager_v1(enrollment: StrategyEnrollmentV2) -> OperatorControlV1:
    """Stop strategy management without changing the Saxo position."""
    _require_live(enrollment)
    set_auto_manage_enabled_v1(enrollment, False)
    return _save(enrollment, MODE_STOPPED, reason="USER_OPERATOR_STOP_KEEP_POSITION")


def close_and_stop_automanager_v1(
    enrollment: StrategyEnrollmentV2,
    observation: PositionObservationV2 | None,
) -> OperatorControlV1:
    """Go FLAT through the shared CLOSE lifecycle and stay stopped afterwards."""
    return _request_flat_v1(
        enrollment, observation,
        transitional_mode=MODE_STOPPING_CLOSE,
        final_mode=MODE_STOPPED,
        signal="USER_OPERATOR_CLOSE_AND_STOP",
    )


__all__ = [
    "MODE_PAUSED", "MODE_PAUSING", "MODE_RUNNING", "MODE_STOPPED", "MODE_STOPPING_CLOSE",
    "OperatorControlV1", "close_and_stop_automanager_v1", "effective_operator_control_v1",
    "ensure_operator_control_schema_v1", "load_operator_control_v1", "pause_automanager_v1",
    "start_automanager_v1", "stop_automanager_v1",
]
