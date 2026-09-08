from __future__ import annotations

from threading import Lock

from autotrader_fast_live_runtime_v2 import ensure_fast_live_schema_v2
from autotrader_mtf_flip_live_runtime_v2 import ensure_mtf_flip_live_schema_v2
from autotrader_mtf_live_runtime_v2 import ensure_mtf_live_schema_v2
from autotrader_mtf_short_live_runtime_v2 import ensure_mtf_short_live_schema_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from database import connect


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


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
        _SCHEMA_READY = True


def _control_row_v1(enrollment: StrategyEnrollmentV2):
    ensure_manage_control_schema_v1()
    with connect() as db:
        return db.execute(
            """
            SELECT auto_manage_enabled, position_management_enabled
            FROM pg_v2_autotrader_product_manage_control
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
        ).fetchone()


def auto_manage_enabled_v1(enrollment: StrategyEnrollmentV2) -> bool:
    """Return AutoTrade strategy-signal authority for one exact product.

    Legacy rows default to ON so this migration never silently disables an already
    active controller. Position-management authority is tracked separately.
    """
    row = _control_row_v1(enrollment)
    if row is None:
        return True
    value = row.get("auto_manage_enabled") if isinstance(row, dict) else row[0]
    return bool(value)


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


def set_auto_manage_enabled_v1(
    enrollment: StrategyEnrollmentV2,
    enabled: bool,
) -> bool:
    """Toggle AutoTrade strategy authority while keeping manual BUY/SELL usable.

    AutoTrade can only be enabled while position management is enabled. OFF supersedes
    only unstarted strategy requests; accepted/uncertain broker work is never cancelled
    or retried here. Runtime signal state is reset on both edges.
    """
    ensure_manage_control_schema_v1()
    value = bool(enabled)
    if value and not position_management_enabled_v1(enrollment):
        raise ValueError("AutoTrade requires Manage position to be ON")
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
                  AND signal NOT LIKE 'USER_TARGET_%'
                """,
                (enrollment.pilot_key,),
            )
    _reset_signal_runtime_v1(enrollment.pilot_key)
    return value


def set_position_management_enabled_v1(
    enrollment: StrategyEnrollmentV2,
    enabled: bool,
) -> bool:
    """Toggle exact-position management authority independently from AutoTrade.

    Turning management OFF also turns AutoTrade OFF and supersedes only unstarted
    strategy-origin requests. Manual target requests remain available so the user can
    still explicitly command BUY/SELL through the normal execution lifecycle.
    """
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
                  AND signal NOT LIKE 'USER_TARGET_%'
                """,
                (enrollment.pilot_key,),
            )
    if not value:
        _reset_signal_runtime_v1(enrollment.pilot_key)
    return value


__all__ = [
    "auto_manage_enabled_v1",
    "ensure_manage_control_schema_v1",
    "position_management_enabled_v1",
    "set_auto_manage_enabled_v1",
    "set_position_management_enabled_v1",
]
