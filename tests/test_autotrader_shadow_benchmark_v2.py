from __future__ import annotations

import pytest

from autotrader_macd_dry_run_v2 import SIGNAL_DOWN, SIGNAL_UP
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_shadow_benchmark_v2 import (
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    apply_shadow_return_v2,
    target_state_for_signal_v2,
)
from autotrader_strategy_catalog_v2 import MACD_LONG_FLAT_STRATEGY_V2


def test_both_macd_strategies_share_bullish_long_target():
    assert target_state_for_signal_v2(MACD_FLIP_STRATEGY_V2, SIGNAL_UP) == STATE_LONG
    assert target_state_for_signal_v2(MACD_LONG_FLAT_STRATEGY_V2, SIGNAL_UP) == STATE_LONG


def test_bearish_cross_is_the_only_policy_difference():
    assert target_state_for_signal_v2(MACD_FLIP_STRATEGY_V2, SIGNAL_DOWN) == STATE_SHORT
    assert target_state_for_signal_v2(MACD_LONG_FLAT_STRATEGY_V2, SIGNAL_DOWN) == STATE_FLAT


def test_shadow_equity_uses_same_price_return_with_signed_exposure():
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_LONG, price_return=0.10) == pytest.approx(550.0)
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_SHORT, price_return=0.10) == pytest.approx(450.0)
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_FLAT, price_return=0.10) == pytest.approx(500.0)


def test_shadow_benchmark_never_creates_credit_after_equity_is_exhausted():
    assert apply_shadow_return_v2(equity=100.0, position_state=STATE_LONG, price_return=-2.0) == 0.0
