from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import (
    MacdTrailingConfigV3,
    macd_trailing_target_v3,
    replay_macd_trailing_targets_v3,
)


def _obs(spread):
    return MacdObservationV2(datetime(2026, 9, 22, tzinfo=timezone.utc), spread, 0.0)


def test_positive_macd_adds_one_tranche_per_observation():
    config = MacdTrailingConfigV3(tranche=0.01, max_inventory=0.03)
    decisions = replay_macd_trailing_targets_v3((_obs(.1), _obs(.2), _obs(.3), _obs(.4)), config=config)
    assert [item.target.amount for item in decisions] == pytest.approx([.01, .02, .03, .03])
    assert decisions[-1].action == "HOLD_MAX"


def test_reversal_walks_inventory_down_before_crossing_short():
    config = MacdTrailingConfigV3(tranche=.01, max_inventory=.05)
    decisions = replay_macd_trailing_targets_v3(
        (_obs(-.2), _obs(-.2), _obs(-.2), _obs(-.2)),
        config=config,
        initial_target=TargetInventoryV3(.02),
    )
    assert [item.target.amount for item in decisions] == pytest.approx([.01, 0, -.01, -.02])
    assert decisions[0].action == "REDUCE"
    assert decisions[1].action == "REDUCE"
    assert decisions[2].action == "ADD"


def test_deadband_holds_inventory():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(.02),
        observation=_obs(.001),
        config=MacdTrailingConfigV3(deadband=.01),
    )
    assert decision.target.amount == pytest.approx(.02)
    assert decision.action == "HOLD"


def test_invalid_tranche_configuration_fails_closed():
    with pytest.raises(ValueError):
        MacdTrailingConfigV3(tranche=0)
    with pytest.raises(ValueError):
        MacdTrailingConfigV3(tranche=.02, max_inventory=.01)


def test_hard_opposite_reversal_flattens_entire_target():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(.05),
        previous_observation=_obs(.02),
        observation=_obs(-.05),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10, hard_reversal_ratio=2.0),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "HARD_REVERSAL_FLAT"


def test_ordinary_reversal_still_reduces_one_tranche():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(.05),
        previous_observation=_obs(.04),
        observation=_obs(-.05),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10, hard_reversal_ratio=2.0),
    )
    assert decision.target.amount == pytest.approx(.04)
    assert decision.action == "REDUCE"
