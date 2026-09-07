from __future__ import annotations

from threading import Lock

from database import connect, using_postgres


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False

# PostgreSQL generated this name for the original table-level
# UNIQUE(account_id, uic, asset_type, strategy_key) constraint. That invariant was
# correct while one strategy could only ever have one pilot on a product. Strategy
# activation cohorts deliberately preserve multiple *historical* pilots for the same
# strategy, so the historical uniqueness must be retired. The existing partial unique
# index pg_v2_autotrader_one_live_strategy_per_product_idx remains the authority for
# the safety-critical invariant: at most one enabled LIVE_MANAGE controller per exact
# account + UIC + AssetType.
_LEGACY_STRATEGY_HISTORY_CONSTRAINT = (
    "pg_v2_autotrader_strategy_enr_account_id_uic_asset_type_str_key"
)


def ensure_strategy_activation_cohort_schema_v1() -> None:
    """Allow immutable repeat strategy cohorts without weakening LIVE exclusivity.

    This migration changes only historical enrollment cardinality. It does not change
    execution authority, Product Admission, OPEN/CLOSE gates, or the partial unique
    index that prevents two active LIVE controllers on one exact Saxo product.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not using_postgres():
        raise RuntimeError("strategy activation cohorts require PostgreSQL")
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect() as db:
            db.execute(
                f"ALTER TABLE pg_v2_autotrader_strategy_enrollments "
                f"DROP CONSTRAINT IF EXISTS {_LEGACY_STRATEGY_HISTORY_CONSTRAINT}"
            )
            # Re-assert the safety-critical active-controller invariant explicitly.
            # This is idempotent and intentionally narrower than the retired history
            # constraint because disabled cohorts must be allowed to coexist.
            db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS pg_v2_autotrader_one_live_strategy_per_product_idx
                ON pg_v2_autotrader_strategy_enrollments(account_id, uic, asset_type)
                WHERE enabled = TRUE AND execution_mode = 'LIVE_MANAGE'
                """
            )
        _SCHEMA_READY = True


__all__ = ["ensure_strategy_activation_cohort_schema_v1"]
