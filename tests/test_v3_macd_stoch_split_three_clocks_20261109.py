"""Isolated three-clock MACD+Stoch V2.1 variants: no changes to original."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_v3_macd_stoch_v21_split_v1 as split
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_registry_v1 import (
    strategy_v3, live_config_issues_v3, sim_config_issues_v3,
)
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3
from autotrader_v3_config_v1 import (
    AutoTraderConfigV3, save_autotrader_config_v3, load_autotrader_config_v3,
)
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2

ZERO = datetime(2026, 11, 9, tzinfo=timezone.utc)


def sample_bars(length=1100):
    return tuple(SimpleNamespace(
        bar_time=ZERO + timedelta(minutes=i),
        open=100+i*0.01, high=100+i*0.01+0.03,
        low=100+i*0.01-0.03, close=100+i*0.01,
        market_name="Tech100", volume=None,
    ) for i in range(length))


def obs():
    return SimpleNamespace(bar_time=ZERO+timedelta(minutes=1060),
                           closed_at=ZERO+timedelta(minutes=1060),
                           spread=0.7)


def decision(amount, action="OPEN"):
    return MacdStochV2DecisionV3(TargetInventoryV3(amount),action,"base",0.7,0.8,0.7,0.9)


def run(side, current=0):
    f=split.long_flat_target_v3 if side==1 else split.short_flat_target_v3
    return f(current_target=TargetInventoryV3(current),observation=obs(),
             regime_timeframe_minutes=30,exit_timeframe_minutes=2,
             market_name="Tech100",source_bars=(),bars=(),
             config=MacdTrailingConfigV3())


def test_separate_ids_and_original_still_present():
    assert split.LONG_KEY_V3 != split.SHORT_KEY_V3
    for key in split.SPLIT_KEYS_V3:
        assert key in STRATEGIES_V3 and STRATEGIES_V3[key].live_route_enabled
        assert strategy_v3(key).runtime_ready
        assert live_config_issues_v3(strategy_key=key,timeframe="1m",
            control_mode="Manuell",modifiers=(),exit_timeframe="2m",
            regime_timeframe="30m")==()
        assert sim_config_issues_v3(strategy_key=key,timeframe="1m",
            control_mode="Manuell",modifiers=(),exit_timeframe="5m",
            regime_timeframe="30m")==()
    assert "macd-stoch-v2-1" in STRATEGIES_V3
    assert "split" not in Path("autotrader_v3_macd_stoch_v21.py").read_text()


def test_full_closed_30m_no_partial_bucket():
    rows=sample_bars()
    bars=split._completed_bars(rows,timeframe=30,
          cutoff=ZERO+timedelta(minutes=1055),market="Tech100")
    assert len(bars)==35
    assert bars[-1].bar_time==ZERO+timedelta(minutes=1020)
    assert split._latest_macd(rows,minutes=30,
          cutoff=ZERO+timedelta(minutes=1055),market="Tech100") is not None
    # 34 full 30m bars are not sufficient to claim a valid macro regime.
    assert split._latest_macd(rows,minutes=30,
          cutoff=ZERO+timedelta(minutes=1040),market="Tech100") is None


def test_no_future_data_can_affect_past_30m():
    rows=sample_bars()
    stamp=ZERO+timedelta(minutes=1050)
    a=split._latest_macd(rows[:1050],minutes=30,cutoff=stamp,market="Tech100")
    extension=tuple(SimpleNamespace(
        bar_time=ZERO+timedelta(minutes=1100+i),
        open=200.,high=200.,low=1.,close=1.,
        market_name="Tech100",volume=None) for i in range(50))
    b=split._latest_macd(rows+extension,minutes=30,cutoff=stamp,market="Tech100")
    assert a==b


@pytest.mark.parametrize("side",[-1,1])
def test_only_authorized_direction_enters(monkeypatch,side):
    monkeypatch.setattr(split,"_latest_macd",lambda *args, **kwargs: side*0.4)
    monkeypatch.setattr(split,"macd_stoch_v21_target_v3",
                        lambda **kwargs: decision(side*.01))
    result=run(side)
    assert result.target.amount==pytest.approx(side*.01)
    assert result.action=="OPEN"
    monkeypatch.setattr(split,"macd_stoch_v21_target_v3",
                        lambda **kwargs: decision(-side*.01))
    result=run(side)
    assert result.target.amount==0
    assert result.action=="WAIT_ALLOWED_SIDE"


@pytest.mark.parametrize("side",[-1,1])
def test_slow_exit_holds_through_opposed_fast_signal(monkeypatch,side):
    monkeypatch.setattr(split,"_latest_macd",lambda *args, **kwargs: side*.4)
    monkeypatch.setattr(split,"macd_stoch_v21_target_v3",
                        lambda **kwargs: decision(0., "OPPOSITE_FLAT"))
    result=run(side,current=side*.02)
    assert result.target.amount==pytest.approx(side*.02)
    assert result.action=="HOLD_SLOW_EXIT"


@pytest.mark.parametrize("side",[-1,1])
def test_2m_exit_and_regime_close_without_flipping(monkeypatch,side):
    def macd(*args, **kw):
        return side*.3 if kw["minutes"]==30 else -side*.1
    monkeypatch.setattr(split,"_latest_macd",macd)
    result=run(side,current=side*.03)
    assert result.action=="EXIT_MACD_FLAT" and result.target.amount==0
    monkeypatch.setattr(split,"_latest_macd",
                        lambda *args, **kwargs: -side*.3)
    result=run(side,current=side*.03)
    assert result.action=="REGIME_FLAT" and result.target.amount==0


def test_missing_regime_fail_flat_no_data(monkeypatch):
    assert run(1,current=.01).target.amount==0
    assert run(-1,current=-.01).target.amount==0


def test_split_exit_clock_persisted_independently(tmp_path):
    db=str(tmp_path/"v3.sqlite")
    config=AutoTraderConfigV3("test",strategy_key=split.LONG_KEY_V3,
                timeframe="1m",regime_timeframe="30m",exit_timeframe="5m")
    save_autotrader_config_v3(config,db_path=db)
    assert load_autotrader_config_v3("test",db_path=db)==config
    assert AutoTraderConfigV3("other").exit_timeframe=="2m"


def test_legal_saxo_unit_sizing_matches_frozen_v21():
    rules=EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None)
    existing=strategy_amount_config_v3(strategy_key="macd-stoch-v2-1",rules=rules)
    for key in split.SPLIT_KEYS_V3:
        assert strategy_amount_config_v3(strategy_key=key,rules=rules)==existing
