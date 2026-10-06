from pathlib import Path
from types import SimpleNamespace

import autotrader_v3_instance_registry_v1 as registry
import autotrader_v3_live_runtime_v1 as runtime
from autotrader_engine_account_ownership_v1 import ENGINE_V3, claim_account_v1
from autotrader_v3_live_authority_v1 import set_live_authority_v3
from autotrader_v3_order_guard_v1 import pending_order, reserve


def _template(account="autotrader", uic=4912):
    return SimpleNamespace(
        account_id=account,
        uic=uic,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS",
    )


def _instance(account, *, db_path, uic=4912):
    return registry.create_v3_instance_v1(
        account_id=account,
        template=_template(account=account, uic=uic),
        db_path=db_path,
    )


def test_live_runtime_discovers_two_owned_armed_instances_independently(tmp_path):
    db=str(tmp_path/"v3.db")
    first=_instance("autotrader",db_path=db)
    second=_instance("lager",db_path=db)
    for item in (first,second):
        claim_account_v1(item.account_id,ENGINE_V3,item.instance_id,db_path=db)
        set_live_authority_v3(item.instance_id,True,db_path=db)

    active=runtime._load_owned_armed_runtime_instances_v3(db_path=db)

    assert {item.pilot_key for item in active} == {first.instance_id,second.instance_id}
    assert {item.account_id for item in active} == {"autotrader","lager"}


def test_live_runtime_skips_unarmed_instance(tmp_path):
    db=str(tmp_path/"v3.db")
    armed=_instance("autotrader",db_path=db)
    unarmed=_instance("lager",db_path=db)
    for item in (armed,unarmed):
        claim_account_v1(item.account_id,ENGINE_V3,item.instance_id,db_path=db)
    set_live_authority_v3(armed.instance_id,True,db_path=db)

    active=runtime._load_owned_armed_runtime_instances_v3(db_path=db)

    assert tuple(item.pilot_key for item in active) == (armed.instance_id,)


def test_live_runtime_fails_closed_on_account_owner_mismatch(tmp_path):
    db=str(tmp_path/"v3.db")
    item=_instance("autotrader",db_path=db)
    claim_account_v1(item.account_id,ENGINE_V3,"different-v3-instance",db_path=db)
    set_live_authority_v3(item.instance_id,True,db_path=db)

    active=runtime._load_owned_armed_runtime_instances_v3(db_path=db)

    assert active == ()
    with runtime.connect(db) as conn:
        row=conn.execute(
            "SELECT status,detail FROM autotrader_v3_live_runtime_state WHERE trader_id=?",
            (item.instance_id,),
        ).fetchone()
    status=row["status"] if isinstance(row,dict) else row[0]
    detail=row["detail"] if isinstance(row,dict) else row[1]
    assert status == "BLOCKED"
    assert "ownership mismatch" in detail


def test_pending_order_on_one_account_does_not_lock_another_instance(tmp_path):
    db=str(tmp_path/"v3.db")
    first=_instance("autotrader",db_path=db)
    second=_instance("lager",db_path=db)
    reserve(
        request_key="req-a",
        trader_id=first.instance_id,
        account_id=first.account_id,
        uic=first.uic,
        asset_type=first.asset_type,
        expected_inventory=0.01,
        submitted_amount=0.01,
        submitted_side="Buy",
        db_path=db,
    )

    assert pending_order(
        account_id=first.account_id,uic=first.uic,asset_type=first.asset_type,db_path=db
    ) is not None
    assert pending_order(
        account_id=second.account_id,uic=second.uic,asset_type=second.asset_type,db_path=db
    ) is None


def test_bootstrap_preserves_existing_production_instance_identity(monkeypatch,tmp_path):
    db=str(tmp_path/"v3.db")
    legacy=SimpleNamespace(
        pilot_key="production-v3-pilot",
        account_id="autotrader",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS",
    )
    monkeypatch.setattr(registry,"load_active_strategy_enrollments_v2",lambda:(legacy,))

    instances=registry.bootstrap_v3_instances_from_enrollments_v1(db_path=db)

    assert len(instances) == 1
    assert instances[0].instance_id == legacy.pilot_key
    assert instances[0].account_id == legacy.account_id


def test_live_runtime_no_longer_discovers_from_v2_enrollments():
    source=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "load_v3_runtime_instances_v1" in source
    assert "load_active_strategy_enrollments_v2" not in source
    assert "EXECUTION_MODE_LIVE" not in source
    assert "load_account_owner_v1" in source
