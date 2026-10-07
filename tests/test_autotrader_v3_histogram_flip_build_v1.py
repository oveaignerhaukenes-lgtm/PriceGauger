from datetime import datetime, timezone

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_flip_build_v1 import macd_histogram_flip_build_target_v3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3


def _obs(spread: float, minute: int) -> MacdObservationV2:
    return MacdObservationV2(
        bar_time=datetime(2026, 10, 7, 12, minute, tzinfo=timezone.utc),
        macd=float(spread),
        signal=0.0,
    )


def _decision(current: float, previous: float, latest: float):
    return macd_histogram_flip_build_target_v3(
        current_target=TargetInventoryV3(current),
        previous_observation=_obs(previous, 0),
        observation=_obs(latest, 2),
        config=MacdHistogramConfigV3(tranche=0.01, max_inventory=0.10),
    )


def test_short_flips_directly_to_one_long_tranche():
    decision = _decision(-0.08, -0.30, -0.20)
    assert decision.target.amount == 0.01
    assert decision.action == "FLIP"


def test_long_flips_directly_to_one_short_tranche():
    decision = _decision(0.07, 0.30, 0.20)
    assert decision.target.amount == -0.01
    assert decision.action == "FLIP"


def test_same_direction_builds_one_tranche_per_bar():
    assert _decision(0.01, 0.10, 0.20).target.amount == 0.02
    assert _decision(-0.01, -0.10, -0.20).target.amount == -0.02


def test_unchanged_histogram_holds():
    decision = _decision(-0.04, -0.20, -0.20)
    assert decision.target.amount == -0.04
    assert decision.action == "HOLD"


def test_runtime_registry_contains_flip_build():
    from autotrader_v3_macd_histogram_flip_build_v1 import STRATEGY_KEY_V3
    from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3
    assert STRATEGY_KEY_V3 in STRATEGIES_V3
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled is True


def test_catalog_maps_flip_build_to_runtime_key():
    from autotrader_v3_registry_v1 import strategy_v3
    spec = strategy_v3("macd-histogram-flip-build")
    assert spec.runtime_key == "macd-histogram-flip-build-v1"
    assert spec.runtime_ready is True


def test_flip_target_uses_existing_cross_flat_execution_contract():
    from autotrader_v3_domain import AccountBoundaryV3
    from autotrader_v3_execution_plan_v1 import plan_execution_v3
    from autotrader_v3_pipeline_v1 import TraderV3, evaluate_trader_v3

    trader = TraderV3(
        "t",
        AccountBoundaryV3("A", 4912, "CfdOnIndex"),
        "macd-histogram-flip-build-v1",
    )
    snapshot = evaluate_trader_v3(
        trader=trader,
        base_target=TargetInventoryV3(0.01),
        actual_inventory=TargetInventoryV3(-0.08),
    ).snapshot
    plan = plan_execution_v3(snapshot)
    assert [step.action for step in plan.steps] == ["CLOSE", "CONFIRM_FLAT", "OPEN"]
    assert plan.steps[0].amount == 0.08
    assert plan.steps[2].amount == 0.01
