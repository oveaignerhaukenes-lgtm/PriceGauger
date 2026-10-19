"""Rytmebygg v1: baseline-parity, timing, risk and account-isolation tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_v3_macd_stoch_v2 as baseline
import autotrader_v3_macd_stoch_v21 as baseline_v21_module
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_rhythm_build_v1 import (
    STRATEGY_KEY_V3, macd_stoch_rhythm_build_target_v3, rhythm_build_evidence_v1,
)
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_registry_v1 import (
    live_config_issues_v3, sim_config_issues_v3, strategy_v3,
)
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2


START = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


def bars_from_closes(closes, *, gap_after=None):
    """Canonical 1m completed OHLC with strictly increasing UTC starts."""
    out = []
    for i, price in enumerate(closes):
        offset = 2 if gap_after is not None and i > gap_after else 0
        out.append(SimpleNamespace(
            bar_time=START + timedelta(minutes=i + offset),
            open=float(price), high=float(price) + 0.05,
            low=float(price) - 0.05, close=float(price),
        ))
    return tuple(out)


def obs(value, stamp):
    return MacdObservationV2(bar_time=stamp, macd=float(value), signal=0.0)


@pytest.fixture()
def scores(monkeypatch):
    # Isolate INVENTORY logic by replacing indicator math for both controls
    # and new policy with identical input evidence on the same bars.
    def deterministic_score(observation, bars):
        if observation is None:
            return None
        return (float(observation.spread), 0.6, 0.4)
    monkeypatch.setattr(baseline, "composite_score_v3", deterministic_score)
    monkeypatch.setattr(baseline_v21_module, "composite_score_v3", deterministic_score)


def decide(closes, *, size, score=0.8, previous=0.8,
           cfg=MacdTrailingConfigV3(), gap_after=None):
    candles = bars_from_closes(closes, gap_after=gap_after)
    current = obs(score, candles[-1].bar_time)
    prior = obs(previous, candles[-2].bar_time)
    return macd_stoch_rhythm_build_target_v3(
        current_target=TargetInventoryV3(size),
        observation=current, previous_observation=prior,
        bars=candles, config=cfg,
    )


def test_rhythm_classifies_consistent_trend_vs_chop_vs_missing_session():
    trend = bars_from_closes([100+i*0.12 for i in range(42)])
    t = rhythm_build_evidence_v1(trend, observation_time=trend[-1].bar_time)
    assert t.available and t.confirmed_direction == 1 and not t.choppy
    chop = bars_from_closes([100 + (i % 2)*.4 for i in range(42)])
    c = rhythm_build_evidence_v1(chop, observation_time=chop[-1].bar_time)
    assert c.available and c.choppy and c.confirmed_direction == 0
    gap = bars_from_closes([100+i*.12 for i in range(42)], gap_after=38)
    assert not rhythm_build_evidence_v1(gap).available
    with pytest.raises(TypeError):
        # No fallback to invented directional evidence for absent bars.
        float(t)  # dataclass is descriptive, not a numeric trading score


def test_same_v2_first_entry_in_stable_market(scores):
    closes = [100+i*0.13 for i in range(45)]
    result = decide(closes, size=0.)
    assert result.action == "OPEN"
    assert result.target.amount == pytest.approx(.01)


@pytest.mark.parametrize("sign", [-1., 1.])
def test_builds_one_increment_only_after_price_confirms(scores, sign):
    closes = [100 + sign*i*.15 for i in range(45)]
    prior = sign*.9
    result = decide(closes, size=sign*.01, score=prior, previous=prior)
    assert result.action == "BUILD"
    assert result.target.amount == pytest.approx(sign*.02)


def test_whipsaw_trims_full_inventory_to_exactly_one_tranche(scores):
    prices = [100 + (i%2)*.6 for i in range(46)]
    result = decide(prices, size=.08, score=.8, previous=.8)
    assert result.action == "TRIM_CHOP"
    assert result.target.amount == pytest.approx(.01)
    short = decide(prices, size=-.09, score=-.8, previous=-.8)
    assert short.action == "TRIM_CHOP"
    assert short.target.amount == pytest.approx(-.01)


def test_chop_no_new_entry_but_one_tranche_is_held(scores):
    prices = [100 + (i%2)*.6 for i in range(46)]
    assert decide(prices, size=0.).action == "HOLD_CHOP_FLAT"
    result = decide(prices, size=.01)
    assert result.action == "HOLD_CHOP_MIN"
    assert result.target.amount == pytest.approx(.01)


def test_direction_break_trims_to_min_even_with_positive_MACD(scores):
    prices=[100+i*.1 for i in range(43)] + [104.4, 104.3, 104.2]
    result = decide(prices, size=.06, score=.8, previous=.8)
    assert result.action == "TRIM_UNCONFIRMED"
    assert result.target.amount == pytest.approx(.01)


def test_full_flat_on_opposing_score_even_if_price_trending(scores):
    rising=[100+i*.12 for i in range(43)]
    opposite=decide(rising, size=.09, score=-.8, previous=.8)
    assert opposite.action == "OPPOSITE_FLAT"
    assert opposite.target.amount == 0.0
    falling=[110-i*.12 for i in range(43)]
    opposite_short=decide(falling, size=-.09, score=.8, previous=-.8)
    assert opposite_short.action == "OPPOSITE_FLAT"
    assert opposite_short.target.amount == 0.0
    deadband=decide(rising, size=.09, score=.03, previous=.9)
    assert deadband.action == "WEAK_FLAT" and deadband.target.amount == 0.0


def test_missing_1m_data_never_adds_and_can_reduce(scores):
    closes=[100+i*.12 for i in range(44)]
    trim=decide(closes, size=.06, gap_after=38)
    assert trim.action == "TRIM_UNKNOWN_RHYTHM"
    assert trim.target.amount == pytest.approx(.01)
    unknown=decide(closes, size=0., gap_after=38)
    assert unknown.target.amount == 0
    assert unknown.action == "HOLD_UNKNOWN_RHYTHM"


def test_v2_and_v21_reference_untouched_and_independent(scores):
    candles=bars_from_closes([100+(i%2)*.6 for i in range(50)])
    current=obs(.8,candles[-1].bar_time)
    prior=obs(.8,candles[-2].bar_time)
    from autotrader_v3_macd_stoch_v2 import macd_stoch_v2_target_v3
    from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
    kwargs=dict(
        current_target=TargetInventoryV3(.02),
        observation=current, previous_observation=prior, bars=candles,
        config=MacdTrailingConfigV3(),
    )
    baseline_v2=macd_stoch_v2_target_v3(**kwargs)
    baseline_v21=macd_stoch_v21_target_v3(**kwargs)
    experimental=macd_stoch_rhythm_build_target_v3(**kwargs)
    assert baseline_v2.action=="BUILD" and baseline_v2.target.amount==pytest.approx(.03)
    assert baseline_v21.action=="HOLD_BUILD_DECELERATING"
    assert experimental.action=="TRIM_CHOP" and experimental.target.amount==pytest.approx(.01)


def test_closed_bar_driver_durable_and_two_control_accounts_unmodified(scores, tmp_path):
    db=str(tmp_path/"rhythm_driver.sqlite")
    def run(key,name,i,closes,score=.8):
        candles=bars_from_closes(closes)
        return evaluate_strategy_bar_v3(
            trader_id=name, strategy_key=key, observation=obs(score,candles[-1].bar_time),
            bars=candles, db_path=db,
        )
    rising=[100+i*.1 for i in range(48)]
    # Three fully independent state cursors; no control-account policy mutation.
    a=run("macd-stoch-v2","control-B",42,rising[:42])
    b=run("macd-stoch-v2","control-H",42,rising[:42])
    x=run(STRATEGY_KEY_V3,"candidate",42,rising[:42])
    assert a.decision.target.amount==b.decision.target.amount==x.decision.target.amount==0
    for length in (43,44):
        a=run("macd-stoch-v2","control-B",length,rising[:length])
        b=run("macd-stoch-v2","control-H",length,rising[:length])
        x=run(STRATEGY_KEY_V3,"candidate",length,rising[:length])
        assert a.decision.target.amount==b.decision.target.amount
    assert a.decision.target.amount==pytest.approx(.02)
    assert x.decision.target.amount==pytest.approx(.02)
    again=run(STRATEGY_KEY_V3,"candidate",44,rising[:44])
    assert not again.is_new
    assert again.decision.target.amount==pytest.approx(.02)


def test_registered_for_live_and_sim_and_restricted_to_1m():
    spec=strategy_v3("macd-stoch-rhythm-build")
    assert spec.runtime_key==STRATEGY_KEY_V3
    assert spec.runtime_ready
    # Runtime route is available; separate account arming remains mandatory.
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled is True
    assert sim_config_issues_v3(strategy_key=spec.key,timeframe="1m",
                                control_mode="Manuell",modifiers=()) == ()
    assert live_config_issues_v3(strategy_key=spec.key,timeframe="1m",
                                 control_mode="Manuell",modifiers=()) == ()
    for timeframe in ("2m","5m","Adaptiv"):
        for validate in (live_config_issues_v3,sim_config_issues_v3):
            issues = validate(strategy_key=spec.key,timeframe=timeframe,
                              control_mode="Manuell",modifiers=())
            assert any("1m-signaler" in reason for reason in issues)
    # The LIVE worker preserves independent account, pending and arming checks.
    live = Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "if not adapter.live_route_enabled" in live


def test_legal_saxo_sizing_and_no_broker_or_db_in_pure_strategy():
    rules=EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1.0,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None,
    )
    sizing=strategy_amount_config_v3(strategy_key=STRATEGY_KEY_V3,rules=rules)
    assert sizing.tranche==pytest.approx(.01)
    assert sizing.max_inventory==pytest.approx(.10)
    source=Path("autotrader_v3_macd_stoch_rhythm_build_v1.py").read_text()
    for bad in ("place_order(", "from database import", "reserve_order_v3",
                "set_live_enabled", "SaxoOrderRequest"):
        assert bad not in source
    live=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "pending_order_v3(" in live
    assert "plan_execution_v3(snapshot)" in live
