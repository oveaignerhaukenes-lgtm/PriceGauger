from types import SimpleNamespace
import pytest
import autotrader_v3_instance_registry_v1 as registry

def _template(account='autotrader',uic=4912):
    return SimpleNamespace(account_id=account,uic=uic,asset_type='CfdOnIndex',market_id=1,instrument_id=2,market_name='US Tech 100 NAS')

def test_two_accounts_create_two_isolated_instances(tmp_path):
    db=str(tmp_path/'v3.db');a=registry.create_v3_instance_v1(account_id='autotrader',template=_template(),db_path=db);b=registry.create_v3_instance_v1(account_id='lager',template=_template(),db_path=db)
    assert a.instance_id!=b.instance_id
    assert {i.account_id for i in registry.load_v3_instances_v1(db_path=db)}=={'autotrader','lager'}

def test_same_account_cannot_be_attached_to_two_instances_even_for_other_instrument(tmp_path):
    db=str(tmp_path/'v3.db');registry.create_v3_instance_v1(account_id='lager',template=_template(),db_path=db)
    try:registry.create_v3_instance_v1(account_id='lager',template=_template(uic=9999),db_path=db)
    except ValueError as exc:assert 'already attached' in str(exc)
    else:raise AssertionError('duplicate Saxo account assignment was accepted')

def test_instance_identity_is_stable_across_recreation(tmp_path):
    db=str(tmp_path/'a.db');first=registry.create_v3_instance_v1(account_id='lager',template=_template(),db_path=db)
    db2=str(tmp_path/'b.db');second=registry.create_v3_instance_v1(account_id='lager',template=_template(),db_path=db2)
    assert first.instance_id==second.instance_id


def _legacy(pilot,account,strategy,mode='LIVE_MANAGE',uic=4912):
    return SimpleNamespace(
        pilot_key=pilot,strategy_key=strategy,execution_mode=mode,
        account_id=account,uic=uic,asset_type='CfdOnIndex',
        market_id=1,instrument_id=2,market_name='US Tech 100 NAS',
    )

def test_legacy_registry_migration_removes_v2_artifact_and_restores_v3_live_identity(tmp_path):
    db=str(tmp_path/'legacy.db')
    v2=_legacy('legacy-v2-pilot','v2-account','macd-30m-long-flat-v1')
    v3=_legacy('production-v3-pilot','v3-account','macd-trailing-v1')
    registry.create_v3_instance_v1(account_id=v2.account_id,template=v2,instance_id=v2.pilot_key,db_path=db)

    registry._migrate_legacy_registry_rows_v1((v2,v3),db_path=db)

    instances=registry.load_v3_instances_v1(db_path=db)
    assert tuple(i.instance_id for i in instances)==(v3.pilot_key,)
    assert instances[0].account_id==v3.account_id
    assert registry._legacy_registry_migration_complete_v1(db_path=db)
    registry._migrate_legacy_registry_rows_v1((v2,v3),db_path=db)
    assert tuple(i.instance_id for i in registry.load_v3_instances_v1(db_path=db))==(v3.pilot_key,)

def test_legacy_registry_migration_does_not_replace_unknown_instance_on_live_account(tmp_path):
    db=str(tmp_path/'conflict.db')
    v3=_legacy('production-v3-pilot','v3-account','macd-trailing-v1')
    registry.create_v3_instance_v1(account_id=v3.account_id,template=v3,instance_id='unknown-existing-instance',db_path=db)

    with pytest.raises(RuntimeError,match='already attached'):
        registry._migrate_legacy_registry_rows_v1((v3,),db_path=db)

    assert not registry._legacy_registry_migration_complete_v1(db_path=db)
    instances=registry.load_v3_instances_v1(db_path=db)
    assert tuple(i.instance_id for i in instances)==('unknown-existing-instance',)

def test_legacy_registry_migration_does_not_promote_v3_shadow_as_live_instance(tmp_path):
    db=str(tmp_path/'shadow.db')
    shadow=_legacy('shadow-v3-pilot','shadow-account','macd-trailing-v1',mode='SHADOW')
    registry._migrate_legacy_registry_rows_v1((shadow,),db_path=db)
    assert registry.load_v3_instances_v1(db_path=db)==()
