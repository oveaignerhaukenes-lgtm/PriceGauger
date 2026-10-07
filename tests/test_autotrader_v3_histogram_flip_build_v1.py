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
