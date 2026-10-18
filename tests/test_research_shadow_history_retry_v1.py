"""Regression for a bounded, research-only retry on missing market history.

No broker adapter is imported here; no LIVE code paths change.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from research_shadow_history_retry_v1 import (
    MissingShadowHistoryRetryV1,
    is_only_missing_shadow_history,
)


def test_missing_history_backoff_is_bounded_and_per_market_and_strategy():
    clock=[10.0]
    retry=MissingShadowHistoryRetryV1(monotonic=lambda:clock[0],retry_seconds=120)
    k={"strategy":"one","db_path":"test.db","source_id":123}
    assert retry.should_attempt(**k)
    retry.record_missing(**k)
    assert not retry.should_attempt(**k)
    assert retry.should_attempt(strategy="two",db_path="test.db",source_id=123)
    assert retry.should_attempt(strategy="one",db_path="other.db",source_id=123)
    assert retry.should_attempt(strategy="one",db_path="test.db",source_id=999)
    clock[0]=129.999
    assert not retry.should_attempt(**k)
    clock[0]=130.0
    assert retry.should_attempt(**k)
    retry.record_missing(**k)
    retry.mark_available(**k)
    assert retry.should_attempt(**k)


@pytest.mark.parametrize("exc,market,expected",[
    (ValueError("no canonical history for Natural Gas"),"Natural Gas",True),
    (ValueError("Cocktail Mode #1 lacks canonical warmup for Natural Gas"),"Natural Gas",True),
    (ValueError("no canonical history for Tech100"),"Natural Gas",False),
    (ValueError("unrelated data failure"),"Natural Gas",False),
    (RuntimeError("no canonical history for Natural Gas"),"Natural Gas",False),
])
def test_only_exact_data_absence_is_backed_off(exc,market,expected):
    assert is_only_missing_shadow_history(exc,market) is expected


@pytest.mark.parametrize("module_name,cycle_name,ensure_name,evaluate_name,cocktail",[
    ("autotrader_macd_dry_run_v2","run_macd_dry_run_cycle_v2",
     "ensure_macd_dry_run_schema_v2","evaluate_market_macd_dry_run_v2",False),
    ("autotrader_fast_15m_shadow_v2","run_fast_15m_shadow_cycle_v2",
     "ensure_fast_15m_shadow_schema_v2","evaluate_market_fast_15m_shadow_v2",False),
    ("autotrader_mtf_entry_shadow_v2","run_mtf_entry_shadow_cycle_v2",
     "ensure_mtf_entry_shadow_schema_v2","evaluate_market_mtf_entry_shadow_v2",False),
    ("autotrader_cocktail_mode_1_shadow_v2","run_cocktail_mode_1_shadow_cycle_v1",
     "ensure_cocktail_mode_1_schema_v1","evaluate_cocktail_instrument_v1",True),
])
def test_shadow_cycle_missing_history_skips_only_research_then_rechecks(
    monkeypatch,module_name,cycle_name,ensure_name,evaluate_name,cocktail,
):
    module=importlib.import_module(module_name)
    clock=[0.0]
    retry=MissingShadowHistoryRetryV1(monotonic=lambda:clock[0],retry_seconds=120)
    monkeypatch.setattr(module,"RETRY",retry)
    monkeypatch.setattr(module,ensure_name,lambda:None)
    sources=[
        SimpleNamespace(instrument_id=5,market_id=1,market_name="Natural Gas"),
        SimpleNamespace(instrument_id=6,market_id=2,market_name="US Tech 100 NAS"),
    ]
    monkeypatch.setattr(module,"list_subscribed_sources_v2",lambda provider:sources)
    if cocktail:
        monkeypatch.setattr(module,"CanonicalMarketBarStoreV2",lambda db_path:object())
    else:
        monkeypatch.setattr(module,"MarketHistoryStore",lambda db_path:object())
    evaluations=[]
    fail=[True]

    def fake_evaluate(**kwargs):
        name=kwargs["market_name"]
        evaluations.append(name)
        if name=="Natural Gas" and fail[0]:
            if cocktail:
                raise ValueError("Cocktail Mode #1 lacks canonical warmup for Natural Gas")
            raise ValueError("no canonical history for Natural Gas")
        if cocktail:
            return SimpleNamespace(mode="NORMAL"),0,0
        return SimpleNamespace(state="FLAT"),()

    monkeypatch.setattr(module,evaluate_name,fake_evaluate)
    cycle=getattr(module,cycle_name)
    first=cycle(db_path="isolated-research-test.db")
    assert first.attempted==2
    assert first.evaluated==1
    assert first.failed==1
    assert first.skipped_missing_history==0
    assert evaluations==["Natural Gas","US Tech 100 NAS"]

    second=cycle(db_path="isolated-research-test.db")
    assert second.attempted==2
    assert second.evaluated==1
    assert second.failed==0
    assert second.skipped_missing_history==1
    assert evaluations==["Natural Gas","US Tech 100 NAS","US Tech 100 NAS"]

    fail[0]=False
    clock[0]=121.0
    third=cycle(db_path="isolated-research-test.db")
    assert third.attempted==2
    assert third.evaluated==2
    assert third.failed==0
    assert third.skipped_missing_history==0
    assert evaluations.count("Natural Gas")==2

    fourth=cycle(db_path="isolated-research-test.db")
    assert fourth.evaluated==2
    assert fourth.skipped_missing_history==0
    assert evaluations.count("Natural Gas")==3


@pytest.mark.parametrize("failure_message",[
    "unrelated P/L error",
    "no canonical history for a different market",
])
def test_other_error_is_not_swallowed_or_cached(monkeypatch,failure_message):
    module=importlib.import_module("autotrader_fast_15m_shadow_v2")
    retry=MissingShadowHistoryRetryV1(monotonic=lambda:0,retry_seconds=120)
    monkeypatch.setattr(module,"RETRY",retry)
    monkeypatch.setattr(module,"ensure_fast_15m_shadow_schema_v2",lambda:None)
    monkeypatch.setattr(module,"MarketHistoryStore",lambda db:object())
    monkeypatch.setattr(module,"list_subscribed_sources_v2",lambda provider:[
        SimpleNamespace(market_id=1,market_name="Natural Gas")
    ])
    calls=[]
    def fail(**kwargs):
        calls.append(True)
        raise ValueError(failure_message)
    monkeypatch.setattr(module,"evaluate_market_fast_15m_shadow_v2",fail)
    for _ in range(2):
        result=module.run_fast_15m_shadow_cycle_v2(db_path="isolated.db")
        assert result.failed==1
        assert result.skipped_missing_history==0
    assert len(calls)==2
