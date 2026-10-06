from types import SimpleNamespace

import pytest

import autotrader_v3_legacy_ownership_migration_v1 as migration
from autotrader_engine_account_ownership_v1 import (
    ENGINE_V3,
    claim_account_v1,
    load_account_owner_v1,
)
from autotrader_v3_live_authority_v1 import set_live_authority_v3
from database import connect


def _legacy(pilot="production-v3-pilot",account="autotrader",strategy="macd-trailing-v1",mode="LIVE_MANAGE",uic=4912):
    return SimpleNamespace(
        pilot_key=pilot,
        strategy_key=strategy,
        execution_mode=mode,
        account_id=account,
        uic=uic,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS",
    )


def _instance(pilot="production-v3-pilot",account="autotrader",uic=4912):
    return SimpleNamespace(
        pilot_key=pilot,
        account_id=account,
        uic=uic,
        asset_type="CfdOnIndex",
    )


def _marker_exists(db):
    with connect(db) as conn:
        row=conn.execute(
            "SELECT migration_key FROM autotrader_v3_ownership_migrations WHERE migration_key=?",
            (migration._MIGRATION_KEY,),
        ).fetchone()
    return row is not None


def _v2_off(_enrollment):
    return SimpleNamespace(live_armed=False)


def test_backfill_claims_preownership_armed_v3_live_identity_once(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    legacy=_legacy()
    item=_instance()
    set_live_authority_v3(item.pilot_key,True,db_path=db)
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(legacy,))
    monkeypatch.setattr(migration,"authority_state_v2",_v2_off)

    claimed=migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)

    assert claimed==(item.pilot_key,)
    owner=load_account_owner_v1(item.account_id,db_path=db)
    assert owner is not None
    assert owner.engine_id==ENGINE_V3
    assert owner.owner_key==item.pilot_key
    assert _marker_exists(db)
    assert migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)==()


def test_backfill_allows_stale_v2_enrollment_when_v2_live_authority_is_off(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    v3=_legacy()
    v2=_legacy(pilot="v2-pilot",strategy="macd-30m-long-flat-v1")
    item=_instance()
    set_live_authority_v3(item.pilot_key,True,db_path=db)
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(v2,v3))
    monkeypatch.setattr(migration,"authority_state_v2",_v2_off)

    claimed=migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)

    assert claimed==(item.pilot_key,)
    owner=load_account_owner_v1(item.account_id,db_path=db)
    assert owner is not None and owner.engine_id==ENGINE_V3 and owner.owner_key==item.pilot_key
    assert _marker_exists(db)


def test_backfill_rejects_actual_v2_live_authority_on_same_account(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    v3=_legacy()
    v2=_legacy(pilot="v2-pilot",strategy="macd-30m-long-flat-v1")
    item=_instance()
    set_live_authority_v3(item.pilot_key,True,db_path=db)
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(v2,v3))
    monkeypatch.setattr(
        migration,
        "authority_state_v2",
        lambda e:SimpleNamespace(live_armed=(e.pilot_key==v2.pilot_key)),
    )

    with pytest.raises(RuntimeError,match="active V2 LIVE authority"):
        migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)

    assert load_account_owner_v1(item.account_id,db_path=db) is None
    assert not _marker_exists(db)


def test_backfill_never_transfers_existing_owner(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    legacy=_legacy()
    item=_instance()
    set_live_authority_v3(item.pilot_key,True,db_path=db)
    claim_account_v1(item.account_id,ENGINE_V3,"other-v3-owner",db_path=db)
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(legacy,))
    monkeypatch.setattr(migration,"authority_state_v2",_v2_off)

    with pytest.raises(RuntimeError,match="owned by V3/other-v3-owner"):
        migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)

    owner=load_account_owner_v1(item.account_id,db_path=db)
    assert owner is not None and owner.owner_key=="other-v3-owner"
    assert not _marker_exists(db)


def test_backfill_rejects_changed_exact_broker_boundary(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    legacy=_legacy(uic=4912)
    item=_instance(uic=9999)
    set_live_authority_v3(item.pilot_key,True,db_path=db)
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(legacy,))
    monkeypatch.setattr(migration,"authority_state_v2",_v2_off)

    with pytest.raises(RuntimeError,match="boundary mismatch"):
        migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)

    assert load_account_owner_v1(item.account_id,db_path=db) is None
    assert not _marker_exists(db)


def test_backfill_does_not_promote_shadow_or_unarmed_identity(monkeypatch,tmp_path):
    db=str(tmp_path/"pg.db")
    shadow=_legacy(mode="SHADOW")
    item=_instance()
    monkeypatch.setattr(migration,"load_active_strategy_enrollments_v2",lambda:(shadow,))
    monkeypatch.setattr(migration,"authority_state_v2",_v2_off)

    assert migration.backfill_legacy_v3_live_ownership_v1((item,),db_path=db)==()
    assert load_account_owner_v1(item.account_id,db_path=db) is None
