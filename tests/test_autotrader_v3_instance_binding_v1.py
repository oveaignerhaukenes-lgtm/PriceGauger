from types import SimpleNamespace

import pytest

import autotrader_v3_instance_binding_v1 as binding
import autotrader_v3_instance_registry_v1 as registry


def _source(*, market_id, market_name, instrument_id, uic, asset_type, display_name):
    return SimpleNamespace(
        market_id=market_id,
        market_name=market_name,
        instrument_id=instrument_id,
        provider="saxo",
        provider_instrument_id=str(uic),
        asset_type=asset_type,
        display_name=display_name,
    )


def test_available_bindings_follow_latest_subscribed_saxo_instrument(monkeypatch):
    monkeypatch.setattr(
        binding,
        "list_subscribed_sources_v2",
        lambda provider=None: (
            _source(market_id=1,market_name="Silver",instrument_id=10,uic=100,asset_type="CfdOnFutures",display_name="old"),
            _source(market_id=1,market_name="Silver",instrument_id=11,uic=101,asset_type="CfdOnFutures",display_name="Silver Dec"),
            _source(market_id=2,market_name="US Tech 100 NAS",instrument_id=20,uic=4912,asset_type="CfdOnIndex",display_name="NAS"),
        ),
    )
    rows=binding.load_available_v3_instrument_bindings_v1()
    silver=next(item for item in rows if item.market_name=="Silver")
    assert silver.instrument_id==11
    assert silver.uic==101
    assert "Silver Dec" in silver.label


def _template(*, market_id=2, market_name="US Tech 100 NAS", instrument_id=20, uic=4912, asset_type="CfdOnIndex"):
    return SimpleNamespace(
        market_id=market_id,
        market_name=market_name,
        instrument_id=instrument_id,
        uic=uic,
        asset_type=asset_type,
    )


def test_unarmed_instance_can_be_replaced_with_silver_boundary(monkeypatch,tmp_path):
    db=str(tmp_path/"v3.db")
    old=registry.create_v3_instance_v1(account_id="silver-account",template=_template(),db_path=db)
    target=binding.V3InstrumentBindingV1(
        market_id=1,market_name="Silver",instrument_id=11,display_name="Silver Dec",
        uic=777,asset_type="CfdOnFutures",
    )
    monkeypatch.setattr(binding,"authority_state_v3",lambda *_args,**_kwargs:SimpleNamespace(live_armed=False,sim_armed=False))
    monkeypatch.setattr(binding,"load_account_owner_v1",lambda *_args,**_kwargs:None)
    monkeypatch.setattr(binding,"pending_order",lambda **_kwargs:None)

    new=binding.replace_unarmed_v3_instance_binding_v1(old,target,db_path=db)

    assert new.instance_id!=old.instance_id
    assert new.account_id=="silver-account"
    assert new.market_name=="Silver"
    assert new.uic==777
    assert registry.load_v3_instances_v1(db_path=db)==(new,)


def test_binding_change_fails_closed_when_live_is_armed(monkeypatch,tmp_path):
    db=str(tmp_path/"v3.db")
    old=registry.create_v3_instance_v1(account_id="silver-account",template=_template(),db_path=db)
    target=binding.V3InstrumentBindingV1(1,"Silver",11,"Silver Dec",777,"CfdOnFutures")
    monkeypatch.setattr(binding,"authority_state_v3",lambda *_args,**_kwargs:SimpleNamespace(live_armed=True,sim_armed=False))
    with pytest.raises(RuntimeError,match="LIVE"):
        binding.replace_unarmed_v3_instance_binding_v1(old,target,db_path=db)
    assert registry.load_v3_instances_v1(db_path=db)==(old,)


def test_registry_same_boundary_keeps_custom_instance_identity(tmp_path):
    db=str(tmp_path/"v3.db")
    old=registry.create_v3_instance_v1(account_id="account",template=_template(),instance_id="custom-production-id",db_path=db)
    same=registry.replace_v3_instance_boundary_v1(instance_id=old.instance_id,template=_template(),db_path=db)
    assert same.instance_id=="custom-production-id"


def test_unarmed_instance_can_be_removed_without_deleting_history_identity(monkeypatch,tmp_path):
    db=str(tmp_path/"v3.db")
    old=registry.create_v3_instance_v1(account_id="account",template=_template(),db_path=db)
    monkeypatch.setattr(binding,"authority_state_v3",lambda *_args,**_kwargs:SimpleNamespace(live_armed=False,sim_armed=False))
    monkeypatch.setattr(binding,"load_account_owner_v1",lambda *_args,**_kwargs:None)
    monkeypatch.setattr(binding,"pending_order",lambda **_kwargs:None)

    binding.remove_unarmed_v3_instance_v1(old,db_path=db)
    assert registry.load_v3_instances_v1(db_path=db) == ()

    restored=registry.create_v3_instance_v1(account_id="account",template=_template(),db_path=db)
    assert restored.instance_id == old.instance_id


def test_instance_removal_fails_closed_while_live_is_armed(monkeypatch,tmp_path):
    db=str(tmp_path/"v3.db")
    old=registry.create_v3_instance_v1(account_id="account",template=_template(),db_path=db)
    monkeypatch.setattr(binding,"authority_state_v3",lambda *_args,**_kwargs:SimpleNamespace(live_armed=True,sim_armed=False))
    with pytest.raises(RuntimeError,match="LIVE"):
        binding.remove_unarmed_v3_instance_v1(old,db_path=db)
    assert registry.load_v3_instances_v1(db_path=db) == (old,)
