from types import SimpleNamespace

import autotrader_v3_instance_registry_v1 as registry


def _template(account="autotrader"):
    return SimpleNamespace(account_id=account,uic=4912,asset_type="CfdOnIndex",market_id=1,instrument_id=2,market_name="US Tech 100 NAS")


def test_two_accounts_create_two_isolated_instances(tmp_path):
    db=str(tmp_path/"v3.db")
    a=registry.create_v3_instance_v1(account_id="autotrader",template=_template(),db_path=db)
    b=registry.create_v3_instance_v1(account_id="lager",template=_template(),db_path=db)
    assert a.instance_id != b.instance_id
    assert {item.account_id for item in registry.load_v3_instances_v1(db_path=db)} == {"autotrader","lager"}


def test_same_account_instrument_cannot_be_added_twice(tmp_path):
    db=str(tmp_path/"v3.db")
    registry.create_v3_instance_v1(account_id="lager",template=_template(),db_path=db)
    try:
        registry.create_v3_instance_v1(account_id="lager",template=_template(),db_path=db)
    except ValueError as exc:
        assert "already has" in str(exc)
    else:
        raise AssertionError("duplicate V3 instance was accepted")


def test_instance_identity_is_stable_across_recreation(tmp_path):
    db=str(tmp_path/"a.db")
    first=registry.create_v3_instance_v1(account_id="lager",template=_template(),db_path=db)
    db2=str(tmp_path/"b.db")
    second=registry.create_v3_instance_v1(account_id="lager",template=_template(),db_path=db2)
    assert first.instance_id == second.instance_id
