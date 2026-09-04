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
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY(account_id, uic, asset_type)
                )
                """
            )
        _SCHEMA_READY = True


def auto_manage_enabled_v1(enrollment: StrategyEnrollmentV2) -> bool:
    """Return signal-authority state for one exact product.

    Existing products default to ON so this control-plane migration never silently
    disables a controller that was already active before Simple Core v1.
    """
    ensure_manage_control_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT auto_manage_enabled
            FROM pg_v2_autotrader_product_manage_control
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (enrollment.account_id, int(enrollment.uic), enrollment.asset_type),
        ).fetchone()
    if row is None:
        return True
    value = row.get("auto_manage_enabled") if isinstance(row, dict) else row[0]
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
    """Toggle strategy signal authority while keeping manual BUY/SELL execution usable.

    OFF supersedes only unstarted strategy requests. Accepted/uncertain broker work is
    never cancelled or retried here. Runtime signal state is cleared on both edges so
    re-enabling bootstraps from the actually observed Saxo exposure instead of replaying
    a signal that predates the user's toggle.
    """
    ensure_manage_control_schema_v1()
    value = bool(enabled)
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_product_manage_control(
                account_id, uic, asset_type, auto_manage_enabled, updated_at
            ) VALUES (?, ?, ?, ?, now())
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
                SET status='SUPERSEDED', block_reason='AUTOMANAGER_OFF', updated_at=now()
                WHERE pilot_key = ? AND status IN ('PENDING','APPROVED')
                """,
                (enrollment.pilot_key,),
            )
    _reset_signal_runtime_v1(enrollment.pilot_key)
    return value


__all__ = [
    "auto_manage_enabled_v1",
    "ensure_manage_control_schema_v1",
    "set_auto_manage_enabled_v1",
]
