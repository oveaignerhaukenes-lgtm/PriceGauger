"""Two independently routed rhythmic candidates. No LIVE broker mutation in tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import autotrader_v3_rhythm_trend_v1 as trend
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_registry_v1 import live_config_issues_v3, sim_config_issues_v3, strategy_v3
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from autotrader_v3_aen2_sticky_regime_v1 import REGIME_BULL, REGIME_BEAR

BASE = datetime(2026, 10, 19, tzinfo=timezone.utc)


def feed(n=181, *, direction=1, gap=None):
    candles=[]
    for i in range(n):
        if i == gap:
            continue
        mid=100+direction*i*.1
        candles.append(SimpleNamespace(
            bar_time=(BASE+timedelta(minutes=i)).isoformat(),
            open=mid-direction*.05,high=mid+.09,low=mid-.09,close=mid))
    return tuple(candles)


def decide(candles, *, inventory=0):
    stamp=datetime.fromisoformat(candles[-1].bar_time)
    obs=MacdObservationV2(bar_time=stamp,macd=1,signal=0)
    return trend.rhythm_trend_target_v3(
        current_target=TargetInventoryV3(inventory),
        observation=obs,bars=candles,source_bars=candles,
        market_name="US Tech 100",
        config=MacdHistogramConfigV3(tranche=.01,max_inventory=.1))


@pytest.fixture
def macro(monkeypatch):
    side=[1]
    monkeypatch.setattr(trend,"classify_sticky_regime_v3",
        lambda **kw: SimpleNamespace(regime=REGIME_BULL if side[0]>0 else REGIME_BEAR))
    return side


def test_catalog_both_are_live_routable_but_not_autoarmed():
    for key in ("macd-stoch-rhythm-build","rhythm-trend-1"):
        spec=strategy_v3(key)
        assert spec.runtime_ready and STRATEGIES_V3[spec.runtime_key].live_route_enabled
        assert live_config_issues_v3(strategy_key=key,timeframe="1m",
            regime_timeframe="15m",control_mode="Manuell",modifiers=())==()
        assert sim_config_issues_v3(strategy_key=key,timeframe="1m",
            regime_timeframe="15m",control_mode="Manuell",modifiers=())==()
        assert any("1m" in s for s in live_config_issues_v3(
            strategy_key=key,timeframe="5m",control_mode="Manuell",
            modifiers=(),regime_timeframe="15m"))
    assert any("15m" in s for s in live_config_issues_v3(
        strategy_key="rhythm-trend-1",timeframe="1m",control_mode="Manuell",
        modifiers=(),regime_timeframe="30m"))


def test_meso_three_complete_candles_and_no_future_leak():
    source=feed()
    at=BASE+timedelta(minutes=180)
    a=trend.meso_structure_v1(source,closed_at=at)
    assert a.available and a.direction==1
    assert not trend.meso_structure_v1(feed(gap=176),closed_at=at).available
    later=tuple(SimpleNamespace(bar_time=(at+timedelta(minutes=i)).isoformat(),
        open=90,high=91,low=89,close=90) for i in range(20))
    assert trend.meso_structure_v1(source+later,closed_at=at)==a
    down=trend.meso_structure_v1(feed(direction=-1),closed_at=at)
    assert down.available and down.direction==-1


def test_new_candidate_opens_one_builds_only_at_5m_and_caps_at_3(macro):
    assert decide(feed(),inventory=0).target.amount==pytest.approx(.01)
    assert decide(feed(),inventory=.01).action=="HOLD"
    assert decide(feed(185),inventory=.01).target.amount==pytest.approx(.02)
    at_cap=decide(feed(185),inventory=.03)
    assert at_cap.action=="HOLD" and at_cap.target.amount==pytest.approx(.03)
    over=decide(feed(185),inventory=.04)
    assert over.action=="TRIM" and over.target.amount==pytest.approx(.03)


def test_macro_reversal_forces_full_flat_before_other_side(macro):
    macro[0]=-1
    d=decide(feed(),inventory=.08)
    assert d.action=="FLAT" and d.target.amount==0
    # No direct reverse from an existing long at opposite macro.
    assert decide(feed(),inventory=0).target.amount==0


def test_meso_opposite_forces_full_flat(macro):
    d=decide(feed(direction=-1),inventory=.05)
    assert d.action=="FLAT" and d.target.amount==0


def test_chop_trims_to_one_and_never_opens_against_5m(macro):
    source=list(feed())
    for i in range(165,181):
        mid=117+(i%2)*.5
        source[i]=SimpleNamespace(bar_time=source[i].bar_time,
             open=mid,high=mid+.1,low=mid-.1,close=mid)
    source=tuple(source)
    assert decide(source,inventory=.07).target.amount==pytest.approx(.01)
    assert decide(source,inventory=0).target.amount==0


def test_missing_meso_macro_or_1m_data_fail_flat(macro):
    assert decide(feed(gap=175),inventory=.03).target.amount==0
    assert decide(feed(gap=179),inventory=.03).target.amount==0
    assert decide(feed(12),inventory=.03).target.amount==0


def test_saxo_legal_increment_and_pure_strategy_does_not_place_orders():
    rules=EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1.0,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None)
    config=strategy_amount_config_v3(strategy_key=trend.STRATEGY_KEY_V3,rules=rules)
    assert config.tranche==pytest.approx(.01)
    assert trend.MAX_TRANCHES==3
    s=Path("autotrader_v3_rhythm_trend_v1.py").read_text()
    for forbidden in ("place_order(", "from database import", "reserve_order_v3(",
                      "SaxoOrderRequest", "set_live_enabled"):
        assert forbidden not in s


def test_shared_broker_guards_and_no_account_mutation_in_pr():
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "if not adapter.live_route_enabled" in runtime
    assert "pending_order_v3(" in runtime
    assert "plan_execution_v3(snapshot)" in runtime
    assert "align_closed_bar_target_v3(" in runtime
    assert "REGIME_RUNTIME_KEYS_V3" in runtime


def test_v3_closed_bar_driver_deduplicates_and_persists_rhythm_trend(macro, tmp_path):
    from autotrader_v3_strategy_registry_v1 import evaluate_strategy_bar_v3

    db=str(tmp_path / "rytmtrend.sqlite")
    config=MacdHistogramConfigV3(tranche=.01,max_inventory=.1)

    def evaluate(count):
        source=feed(count)
        stamp=datetime.fromisoformat(source[-1].bar_time)
        obs=MacdObservationV2(bar_time=stamp,macd=1.0,signal=0)
        return evaluate_strategy_bar_v3(
            trader_id="pilot-new",strategy_key=trend.STRATEGY_KEY_V3,
            observation=obs,bars=source,source_bars=source,
            regime_timeframe_minutes=15,market_name="US Tech 100",
            config=config,db_path=db,
        )

    first=evaluate(181)
    assert first.is_new and first.decision.target.amount==pytest.approx(.01)
    same=evaluate(181)
    assert not same.is_new and same.decision.target.amount==pytest.approx(.01)
    still=evaluate(182)
    assert still.is_new and still.decision.target.amount==pytest.approx(.01)
    built=evaluate(185)
    assert built.is_new and built.decision.target.amount==pytest.approx(.02)
    assert not evaluate(185).is_new
