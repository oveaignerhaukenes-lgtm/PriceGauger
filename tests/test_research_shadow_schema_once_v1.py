"""V2 research schema bootstrap must not run DDL on every shadow cycle."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


CASE = [
    ("autotrader_macd_dry_run_v2","run_macd_dry_run_cycle_v2",
     "run_macd_dry_run_forever_v2","ensure_macd_dry_run_schema_v2"),
    ("autotrader_fast_15m_shadow_v2","run_fast_15m_shadow_cycle_v2",
     "run_fast_15m_shadow_forever_v2","ensure_fast_15m_shadow_schema_v2"),
    ("autotrader_mtf_entry_shadow_v2","run_mtf_entry_shadow_cycle_v2",
     "run_mtf_entry_shadow_forever_v2","ensure_mtf_entry_shadow_schema_v2"),
    ("autotrader_cocktail_mode_1_shadow_v2","run_cocktail_mode_1_shadow_cycle_v1",
     "run_cocktail_mode_1_shadow_forever_v1","ensure_cocktail_mode_1_schema_v1"),
]


@pytest.mark.parametrize("module_name,cycle,forever,ensure",CASE)
def test_direct_research_cycle_still_ensures_schema_but_prepared_cycle_skips_ddl(
    monkeypatch,module_name,cycle,forever,ensure,
):
    mod=importlib.import_module(module_name)
    count=[]
    monkeypatch.setattr(mod,ensure,lambda:count.append("ddl"))
    monkeypatch.setattr(mod,"list_subscribed_sources_v2",lambda provider:[])
    # No real database or broker interaction.
    if hasattr(mod,"MarketHistoryStore"):
        monkeypatch.setattr(mod,"MarketHistoryStore",lambda db_path:object())
    if hasattr(mod,"CanonicalMarketBarStoreV2"):
        monkeypatch.setattr(mod,"CanonicalMarketBarStoreV2",lambda db_path:object())

    direct=getattr(mod,cycle)(db_path="isolated.db")
    assert direct.attempted==0
    assert count==["ddl"]
    prepared=getattr(mod,cycle)(db_path="isolated.db",schema_prepared=True)
    assert prepared.attempted==0
    assert count==["ddl"]
    getattr(mod,cycle)(db_path="isolated.db")
    assert count==["ddl","ddl"]


@pytest.mark.parametrize("module_name,cycle,forever,ensure",CASE)
def test_long_running_research_worker_prepares_tables_once_on_start(
    monkeypatch,module_name,cycle,forever,ensure,
):
    mod=importlib.import_module(module_name)
    calls=[]
    monkeypatch.setattr(mod,ensure,lambda:calls.append("ddl"))
    def fake_cycle(**kwargs):
        calls.append(("cycle",kwargs))
        return SimpleNamespace(attempted=0,evaluated=0,events=0,
                               transitions=0,samples=0,failed=0)
    monkeypatch.setattr(mod,cycle,fake_cycle)
    def stop(*args,**kwargs):
        raise StopIteration("one loop done")
    if module_name=="autotrader_macd_dry_run_v2":
        monkeypatch.setattr(mod.time,"sleep",stop)
    else:
        monkeypatch.setattr(mod,"sleep_to_fixed_start_cadence_v2",stop)
    with pytest.raises(StopIteration):
        getattr(mod,forever)(db_path="isolated.db",interval_seconds=30)
    assert calls==["ddl",("cycle",{"db_path":"isolated.db","schema_prepared":True})]
