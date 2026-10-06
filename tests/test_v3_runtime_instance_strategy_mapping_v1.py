from types import SimpleNamespace

import autotrader_v3_runtime_instances_v1 as runtime_instances
from autotrader_v3_config_v1 import AutoTraderConfigV3


def _instance():
    return SimpleNamespace(
        instance_id="v3-instance",
        account_id="autotrader",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=2,
        market_name="US Tech 100 NAS",
    )


def _load_for(monkeypatch,strategy_key):
    monkeypatch.setattr(
        runtime_instances,
        "bootstrap_v3_instances_from_enrollments_v1",
        lambda **_kwargs:(_instance(),),
    )
    monkeypatch.setattr(
        runtime_instances,
        "load_autotrader_config_v3",
        lambda *_args,**_kwargs:AutoTraderConfigV3(
            trader_id="v3-instance",
            strategy_key=strategy_key,
        ),
    )
    rows=runtime_instances.load_v3_runtime_instances_v1(db_path="ignored.db")
    assert len(rows)==1
    return rows[0]


def test_macd_canonical_config_resolves_to_trailing_runtime_key(monkeypatch):
    row=_load_for(monkeypatch,"macd")
    assert row.strategy_key=="macd-trailing-v1"


def test_histogram_canonical_config_resolves_to_registered_runtime_key(monkeypatch):
    row=_load_for(monkeypatch,"macd-histogram")
    assert row.strategy_key=="macd-histogram-v1"


def test_runtime_not_ready_strategy_keeps_canonical_key_and_remains_blockable(monkeypatch):
    row=_load_for(monkeypatch,"price-macd")
    assert row.strategy_key=="price-macd"
