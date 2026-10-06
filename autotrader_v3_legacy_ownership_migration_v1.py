from __future__ import annotations

import logging

from autotrader_engine_account_ownership_v1 import (
    ENGINE_V2,
    ENGINE_V3,
    claim_account_v1,
    ensure_engine_account_ownership_schema_v1,
    load_account_owner_v1,
)
from autotrader_engine_identity_v1 import enrollment_engine_v1
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    load_active_strategy_enrollments_v2,
    stop_strategy_enrollment_v2,
)
from autotrader_v2_control_plane_v1 import set_live_enabled_v2
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from database import connect

LOGGER=logging.getLogger("pricegauger.autotrader.v3.legacy_ownership")
_MIGRATION_KEY = "2026-10-06-backfill-legacy-v3-live-account-ownership-v1"


def _ensure_migration_schema(*, db_path: str = "pricegauger.db") -> None:
    ensure_engine_account_ownership_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_ownership_migrations(
          migration_key TEXT PRIMARY KEY,
          completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def _marker_exists(*,db_path: str)->bool:
    with connect(db_path) as db:
        row=db.execute(
            "SELECT migration_key FROM autotrader_v3_ownership_migrations WHERE migration_key=?",
            (_MIGRATION_KEY,),
        ).fetchone()
    return row is not None


def _retire_stale_v2_enrollment_v1(enrollment,*,db_path: str)->None:
    """Turn one stale V2 controller fully off before V3 may claim its account.

    V2's own control plane is intentionally used so AutoManage/position authority,
    pending requests and transient runtime state are retired through the canonical
    V2 lifecycle.  The enrollment is disabled only after those authority controls
    are off.  With no ownership row yet, this cannot release or transfer another
    engine's account claim.
    """
    set_live_enabled_v2(enrollment,False,db_path=db_path)
    stop_strategy_enrollment_v2(str(enrollment.pilot_key))
    LOGGER.info(
        "retired stale V2 enrollment pilot=%s account=%s before V3 ownership migration",
        enrollment.pilot_key,enrollment.account_id,
    )


def backfill_legacy_v3_live_ownership_v1(instances, *, db_path: str = "pricegauger.db") -> tuple[str, ...]:
    """Finish the pre-ownership V3 LIVE cutover without permitting dual-engine authority.

    A canonical V3 instance is eligible only when its pre-existing LIVE authority and
    legacy V3 LIVE enrollment agree on instance/account/UIC/asset.  If that account is
    still represented by stale V2 enrollments but has no persistent owner, those V2
    controllers are retired through the V2 control plane first.  V3 ownership is
    claimed only after retirement succeeds.  Any existing different account owner or
    broker-boundary mismatch remains fail-closed.
    """
    _ensure_migration_schema(db_path=db_path)
    if _marker_exists(db_path=db_path):
        return ()

    enrollments=tuple(load_active_strategy_enrollments_v2())
    legacy_v3_live={
        str(e.pilot_key): e for e in enrollments
        if enrollment_engine_v1(e)==ENGINE_V3 and str(e.execution_mode)==EXECUTION_MODE_LIVE
    }
    v2_by_account={}
    for e in enrollments:
        if enrollment_engine_v1(e)==ENGINE_V2:
            v2_by_account.setdefault(str(e.account_id),[]).append(e)

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
        candidates.append((pilot,account))

    claimed=[]
    for pilot,account in candidates:
        current=load_account_owner_v1(account,db_path=db_path)
        if current is not None:
            if current.engine_id != ENGINE_V3 or current.owner_key != pilot:
                raise RuntimeError(
                    f"legacy V3 ownership migration conflict: account {account} "
                    f"is owned by {current.engine_id}/{current.owner_key}"
                )
            continue

        for stale in tuple(v2_by_account.get(account,())):
            _retire_stale_v2_enrollment_v1(stale,db_path=db_path)

        claim_account_v1(account,ENGINE_V3,pilot,db_path=db_path)
        claimed.append(pilot)

    with connect(db_path) as db:
        db.execute(
            "INSERT INTO autotrader_v3_ownership_migrations(migration_key) VALUES(?) "
            "ON CONFLICT(migration_key) DO NOTHING",
            (_MIGRATION_KEY,),
        )
    return tuple(claimed)


__all__=["backfill_legacy_v3_live_ownership_v1"]
