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


def test_negative_but_improving_macd_trails_short_out():
    config = MacdTrailingConfigV3(tranche=.01, max_inventory=.05)
    decisions = replay_macd_trailing_targets_v3(
        (_obs(-.30), _obs(-.20), _obs(-.10)),
        config=config,
        initial_target=TargetInventoryV3(-.03),
    )
    assert [item.target.amount for item in decisions] == pytest.approx([-.04, -.03, -.02])
    assert decisions[1].action == "TRAIL_OUT"
    assert decisions[2].action == "TRAIL_OUT"


def test_short_bullish_impulse_can_cross_zero_to_capture_brief_reversal():
    config = MacdTrailingConfigV3(tranche=.01, max_inventory=.05)
    decisions = replay_macd_trailing_targets_v3(
        (_obs(-.30), _obs(-.15), _obs(-.05), _obs(.02), _obs(.06)),
        config=config,
        initial_target=TargetInventoryV3(-.02),
    )
    assert [item.target.amount for item in decisions] == pytest.approx([-.03, -.02, -.01, 0, .01])
    assert decisions[3].action == "REGIME_CROSS_FLAT"
    assert decisions[-1].action == "ADD_IMPULSE"


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


def test_any_bearish_regime_cross_flattens_entire_long_target():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(.05),
        previous_observation=_obs(.04),
        observation=_obs(-.001),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "REGIME_CROSS_FLAT"


def test_bearish_first_observation_flattens_legacy_long_without_previous_spread():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(.05),
        observation=_obs(-.001),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "REGIME_CROSS_FLAT"


def test_any_bullish_regime_cross_flattens_entire_short_target():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(-.04),
        previous_observation=_obs(-.03),
        observation=_obs(.001),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "REGIME_CROSS_FLAT"


def test_flat_target_never_builds_long_inside_bearish_regime_even_if_spread_improves():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(0),
        previous_observation=_obs(-.05),
        observation=_obs(-.02),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "HOLD_IMPULSE"


def test_flat_target_never_builds_short_inside_bullish_regime_even_if_spread_weakens():
    decision = macd_trailing_target_v3(
        current_target=TargetInventoryV3(0),
        previous_observation=_obs(.05),
        observation=_obs(.02),
        config=MacdTrailingConfigV3(tranche=.01, max_inventory=.10),
    )
    assert decision.target.amount == 0.0
    assert decision.action == "HOLD_IMPULSE"
