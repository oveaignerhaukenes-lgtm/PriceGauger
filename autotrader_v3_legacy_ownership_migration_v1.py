from __future__ import annotations

from autotrader_engine_account_ownership_v1 import (
    ENGINE_V2,
    ENGINE_V3,
    ensure_engine_account_ownership_schema_v1,
)
from autotrader_engine_identity_v1 import enrollment_engine_v1
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_active_strategy_enrollments_v2
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from database import connect

_MIGRATION_KEY = "2026-10-06-backfill-legacy-v3-live-account-ownership-v1"


def _ensure_migration_schema(*, db_path: str = "pricegauger.db") -> None:
    ensure_engine_account_ownership_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_ownership_migrations(
          migration_key TEXT PRIMARY KEY,
          completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def _row_value(row, key: str, index: int):
    return row[key] if isinstance(row, dict) else row[index]


def backfill_legacy_v3_live_ownership_v1(instances, *, db_path: str = "pricegauger.db") -> tuple[str, ...]:
    """Backfill only pre-ownership V3 LIVE authority onto its exact canonical account.

    This bridge exists solely for V3 pilots that were already LIVE-armed before the
    persistent engine-account ownership invariant was introduced.  It never transfers
    an existing claim, never derives authority from registry membership alone, and
    never promotes SIM/SHADOW or V2 enrollments.
    """
    _ensure_migration_schema(db_path=db_path)
    enrollments=tuple(load_active_strategy_enrollments_v2())
    legacy_v3_live={
        str(e.pilot_key): e for e in enrollments
        if enrollment_engine_v1(e)==ENGINE_V3 and str(e.execution_mode)==EXECUTION_MODE_LIVE
    }
    v2_accounts={
        str(e.account_id) for e in enrollments
        if enrollment_engine_v1(e)==ENGINE_V2
    }

    candidates=[]
    for item in tuple(instances):
        pilot=str(item.pilot_key)
        if not live_authority_armed_v3(pilot,db_path=db_path):
            continue
        legacy=legacy_v3_live.get(pilot)
        if legacy is None:
            continue
        account=str(item.account_id)
        if (
            account != str(legacy.account_id)
            or int(item.uic) != int(legacy.uic)
            or str(item.asset_type) != str(legacy.asset_type)
        ):
            raise RuntimeError(
                f"legacy V3 ownership migration boundary mismatch for {pilot}"
            )
        if account in v2_accounts:
            raise RuntimeError(
                f"legacy V3 ownership migration conflict: account {account} is also an active V2 account"
            )
        candidates.append((pilot,account))

    claimed=[]
    with connect(db_path) as db:
        marker=db.execute(
            "SELECT migration_key FROM autotrader_v3_ownership_migrations WHERE migration_key=?",
            (_MIGRATION_KEY,),
        ).fetchone()
        if marker is not None:
            return ()

        pending=[]
        for pilot,account in candidates:
            current=db.execute(
                "SELECT engine_id,owner_key FROM autotrader_engine_account_ownership WHERE account_id=?",
                (account,),
            ).fetchone()
            if current is None:
                pending.append((pilot,account))
                continue
            engine=str(_row_value(current,"engine_id",0))
            owner=str(_row_value(current,"owner_key",1))
            if engine != ENGINE_V3 or owner != pilot:
                raise RuntimeError(
                    f"legacy V3 ownership migration conflict: account {account} is owned by {engine}/{owner}"
                )

        for pilot,account in pending:
            db.execute(
                """INSERT INTO autotrader_engine_account_ownership(
                  account_id,engine_id,owner_key,updated_at)
                  VALUES(?,?,?,CURRENT_TIMESTAMP)""",
                (account,ENGINE_V3,pilot),
            )
            claimed.append(pilot)

        db.execute(
            "INSERT INTO autotrader_v3_ownership_migrations(migration_key) VALUES(?)",
            (_MIGRATION_KEY,),
        )
    return tuple(claimed)


__all__=["backfill_legacy_v3_live_ownership_v1"]
