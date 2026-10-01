from __future__ import annotations

from threading import Lock

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2, save_pilot_margin_config_v2
from autotrader_fast_live_runtime_v2 import ensure_fast_live_schema_v2
from autotrader_mtf_flip_live_runtime_v2 import ensure_mtf_flip_live_schema_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from database import connect


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False
DEFAULT_LIVE_MAX_EFFECTIVE_LEVERAGE_V2 = 5.0
DEFAULT_LIVE_MINIMUM_FREE_CAPITAL_V2 = 0.0


def ensure_manage_control_schema_v1() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        ensure_autotrader_schema_v2()
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_product_manage_control (
                    account_id TEXT NOT NULL,
                    uic BIGINT NOT NULL,
                    asset_type TEXT NOT NULL,
                    auto_manage_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    position_management_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    guard_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                    guard_block_reason TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY(account_id, uic, asset_type)
                )
                """
            )
            db.execute(
                """
                ALTER TABLE pg_v2_autotrader_product_manage_control
                ADD COLUMN IF NOT EXISTS position_management_enabled BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
            db.execute("ALTER TABLE pg_v2_autotrader_product_manage_control ADD COLUMN IF NOT EXISTS guard_blocked BOOLEAN NOT NULL DEFAULT FALSE")
            db.execute("ALTER TABLE pg_v2_autotrader_product_manage_control ADD COLUMN IF NOT EXISTS guard_block_reason TEXT")
        _SCHEMA_READY = True


def _control_row_v1(enrollment: StrategyEnrollmentV2):
    ensure_manage_control_schema_v1()
    with connect() as db:
        return db.execute(
            """
            SELECT auto_manage_enabled, position_management_enabled, guard_blocked, guard_block_reason
            FROM pg_v2_autotrader_product_manage_control
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
        ).fetchone()


def auto_manage_enabled_v1(enrollment: StrategyEnrollmentV2) -> bool:
    """Return AutoTrade strategy-signal authority for one exact product."""
    row = _control_row_v1(enrollment)
    if row is None:
        return True
    value = row.get("auto_manage_enabled") if isinstance(row, dict) else row[0]
    blocked = row.get("guard_blocked") if isinstance(row, dict) else row[2]
    return bool(value) and not bool(blocked)


def position_management_enabled_v1(enrollment: StrategyEnrollmentV2) -> bool:
    """Return whether PriceGauger may own/adopt the exact product position basis."""
    row = _control_row_v1(enrollment)
    if row is None:
        return True
    value = row.get("position_management_enabled") if isinstance(row, dict) else row[1]
    return bool(value)


def _reset_signal_runtime_v1(pilot_key: str) -> None:
    """Forget transient signal state without touching ledger/history/execution attempts."""
    ensure_autotrader_schema_v2()
    ensure_fast_live_schema_v2()
    ensure_mtf_live_schema_v2()
    ensure_mtf_short_live_schema_v2()
    ensure_mtf_flip_live_schema_v2()
    with connect() as db:
        for table in (
            "pg_v2_autotrader_strategy_runtime_state",
            "pg_v2_autotrader_live_pilot_state",
            "pg_v2_autotrader_fast_live_state",
            "pg_v2_autotrader_mtf_live_state",
            "pg_v2_autotrader_mtf_short_live_state",
            "pg_v2_autotrader_mtf_flip_live_state",
        ):
            db.execute(f"DELETE FROM {table} WHERE pilot_key = ?", (str(pilot_key),))


def _ensure_live_margin_envelope_v1(enrollment: StrategyEnrollmentV2) -> None:
    """Provision the execution envelope as part of the V2 LIVE lifecycle.

    Absence is a lifecycle gap and is repaired with the product-wide V2 LIVE default.
    An explicitly disabled existing envelope is *not* silently re-enabled: that remains
    a deliberate fail-closed operator control.
    """
    config = load_pilot_margin_config_v2(enrollment.pilot_key)
    if config is None:
        save_pilot_margin_config_v2(
            pilot_key=enrollment.pilot_key,
            max_effective_leverage=DEFAULT_LIVE_MAX_EFFECTIVE_LEVERAGE_V2,
            minimum_free_capital=DEFAULT_LIVE_MINIMUM_FREE_CAPITAL_V2,
            enabled=True,
        )
        return
    if not config.enabled:
        raise ValueError("MARGIN_ENVELOPE_DISABLED")


def guard_block_state_v1(enrollment: StrategyEnrollmentV2) -> tuple[bool, str | None]:
    row = _control_row_v1(enrollment)
    if row is None:
        return False, None
    blocked = bool(row.get("guard_blocked") if isinstance(row, dict) else row[2])
    reason = row.get("guard_block_reason") if isinstance(row, dict) else row[3]
    return blocked, (None if reason is None else str(reason))


def set_guard_block_v1(enrollment: StrategyEnrollmentV2, reason: str) -> None:
    """Runtime safety interlock. Never rewrites the user's AutoTrade preference."""
    ensure_manage_control_schema_v1()
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_product_manage_control(
                account_id,uic,asset_type,auto_manage_enabled,position_management_enabled,
                guard_blocked,guard_block_reason,updated_at
            ) VALUES (?,?,?,TRUE,TRUE,TRUE,?,now())
            ON CONFLICT (account_id,uic,asset_type) DO UPDATE SET
                guard_blocked=TRUE, guard_block_reason=EXCLUDED.guard_block_reason, updated_at=now()
            """,
            (enrollment.account_id,int(enrollment.uic),enrollment.asset_type,str(reason)),
        )


def clear_guard_block_v1(enrollment: StrategyEnrollmentV2, *, expected_reason: str | None = None) -> bool:
    """Clear only the runtime interlock; user-selected AutoTrade OFF remains OFF."""
    ensure_manage_control_schema_v1()
    with connect() as db:
        if expected_reason is None:
            row=db.execute(
                """UPDATE pg_v2_autotrader_product_manage_control
                   SET guard_blocked=FALSE,guard_block_reason=NULL,updated_at=now()
                   WHERE account_id=? AND uic=? AND asset_type=? AND guard_blocked=TRUE
                   RETURNING 1""",
                (enrollment.account_id,int(enrollment.uic),enrollment.asset_type),
            ).fetchone()
        else:
            row=db.execute(
                """UPDATE pg_v2_autotrader_product_manage_control
                   SET guard_blocked=FALSE,guard_block_reason=NULL,updated_at=now()
                   WHERE account_id=? AND uic=? AND asset_type=? AND guard_blocked=TRUE
                     AND guard_block_reason=?
                   RETURNING 1""",
                (enrollment.account_id,int(enrollment.uic),enrollment.asset_type,str(expected_reason)),
            ).fetchone()
    return row is not None


def set_auto_manage_enabled_v1(
    enrollment: StrategyEnrollmentV2,
    enabled: bool,
) -> bool:
    """Toggle AutoTrade authority; LIVE ON atomically provisions required envelope."""
    ensure_manage_control_schema_v1()
    value = bool(enabled)
    if value and not position_management_enabled_v1(enrollment):
        raise ValueError("AutoTrade requires Manage position to be ON")
    # Do this before granting strategy authority. If provisioning fails, LIVE remains OFF.
    if value:
        _ensure_live_margin_envelope_v1(enrollment)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_product_manage_control(
                account_id, uic, asset_type, auto_manage_enabled,
                position_management_enabled, updated_at
            ) VALUES (?, ?, ?, ?, TRUE, now())
            ON CONFLICT (account_id, uic, asset_type) DO UPDATE SET
                auto_manage_enabled=EXCLUDED.auto_manage_enabled,
                updated_at=now()
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type, value),
        )
        if not value:
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status='SUPERSEDED', block_reason='AUTOTRADE_OFF', updated_at=now()
                WHERE pilot_key = ? AND status IN ('PENDING','APPROVED')
                  AND signal NOT LIKE 'USER_TARGET_%%'
                """,
                (enrollment.pilot_key,),
            )
    _reset_signal_runtime_v1(enrollment.pilot_key)
    return value


def set_position_management_enabled_v1(
    enrollment: StrategyEnrollmentV2,
    enabled: bool,
) -> bool:
    """Toggle exact-position management authority independently from AutoTrade."""
    ensure_manage_control_schema_v1()
    value = bool(enabled)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_product_manage_control(
                account_id, uic, asset_type, auto_manage_enabled,
                position_management_enabled, updated_at
            ) VALUES (?, ?, ?, FALSE, ?, now())
            ON CONFLICT (account_id, uic, asset_type) DO UPDATE SET
                position_management_enabled=EXCLUDED.position_management_enabled,
                auto_manage_enabled=CASE
                    WHEN EXCLUDED.position_management_enabled THEN pg_v2_autotrader_product_manage_control.auto_manage_enabled
                    ELSE FALSE
                END,
                updated_at=now()
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type, value),
        )
        if not value:
            db.execute(
                """
                UPDATE pg_v2_autotrader_execution_requests
                SET status='SUPERSEDED', block_reason='POSITION_MANAGEMENT_OFF', updated_at=now()
                WHERE pilot_key = ? AND status IN ('PENDING','APPROVED')
                  AND signal NOT LIKE 'USER_TARGET_%%'
                """,
                (enrollment.pilot_key,),
            )
    if not value:
        _reset_signal_runtime_v1(enrollment.pilot_key)
    return value


__all__ = [
    "DEFAULT_LIVE_MAX_EFFECTIVE_LEVERAGE_V2",
    "DEFAULT_LIVE_MINIMUM_FREE_CAPITAL_V2",
    "auto_manage_enabled_v1",
    "guard_block_state_v1",
    "set_guard_block_v1",
    "clear_guard_block_v1",
    "ensure_manage_control_schema_v1",
    "position_management_enabled_v1",
    "set_auto_manage_enabled_v1",
    "set_position_management_enabled_v1",
]
