from types import SimpleNamespace

import autotrader_v3_runtime_instances_v1 as runtime_instances


def _instance():
    return SimpleNamespace(
        instance_id="pilot-v3",
        account_id="autotrader",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS",
    )


def _load(monkeypatch,strategy_key):
    monkeypatch.setattr(
        runtime_instances,
        "bootstrap_v3_instances_from_enrollments_v1",
        lambda **_kwargs:(_instance(),),
    )
    monkeypatch.setattr(
        runtime_instances,
        "load_autotrader_config_v3",
        lambda *_args,**_kwargs:SimpleNamespace(strategy_key=strategy_key),
    )
    return runtime_instances.load_v3_runtime_instances_v1(db_path="unused.db")[0]


def test_runtime_instance_resolves_macd_catalog_key_to_live_runtime_key(monkeypatch):
    item=_load(monkeypatch,"macd")
    assert item.strategy_key=="macd-trailing-v1"


def test_runtime_instance_resolves_histogram_catalog_key(monkeypatch):
    item=_load(monkeypatch,"macd-histogram")
    assert item.strategy_key=="macd-histogram-v1"


def test_runtime_instance_keeps_unimplemented_catalog_key_fail_closed(monkeypatch):
    item=_load(monkeypatch,"price-macd")
    assert item.strategy_key=="price-macd"
