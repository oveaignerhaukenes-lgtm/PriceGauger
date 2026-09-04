from __future__ import annotations

from autotrader_macd_hybrid_v1 import (
    HYBRID_STRATEGY_KEYS_V1,
    hybrid_entry_timeframe_for_strategy_v1,
    hybrid_strategy_label_v1,
    hybrid_target_v1,
)
from autotrader_shadow_benchmark_v2 import STATE_FLAT, STATE_LONG, STATE_SHORT
from autotrader_strategy_catalog_v2 import AUTOTRADER_STRATEGIES_V2


def test_hybrid_long_exits_on_fast_bearish_cross_without_slow_entry() -> None:
    assert hybrid_target_v1(
        STATE_LONG,
        cross_1m=STATE_SHORT,
        cross_entry=None,
        entry_regime=STATE_LONG,
        data_gap=False,
    ) == STATE_FLAT


def test_hybrid_short_exits_on_fast_bullish_cross_without_slow_entry() -> None:
    assert hybrid_target_v1(
        STATE_SHORT,
        cross_1m=STATE_LONG,
        cross_entry=None,
        entry_regime=STATE_SHORT,
        data_gap=False,
    ) == STATE_FLAT


def test_hybrid_flat_reenters_on_fast_recovery_when_slow_regime_agrees() -> None:
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=STATE_LONG,
        cross_entry=None,
        entry_regime=STATE_LONG,
        data_gap=False,
    ) == STATE_LONG
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=STATE_SHORT,
        cross_entry=None,
        entry_regime=STATE_SHORT,
        data_gap=False,
    ) == STATE_SHORT


def test_hybrid_flat_does_not_reenter_against_slow_regime() -> None:
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=STATE_LONG,
        cross_entry=None,
        entry_regime=STATE_SHORT,
        data_gap=False,
    ) == STATE_FLAT
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=STATE_SHORT,
        cross_entry=None,
        entry_regime=STATE_LONG,
        data_gap=False,
    ) == STATE_FLAT


def test_hybrid_flat_still_accepts_fresh_entry_timeframe_cross() -> None:
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=None,
        cross_entry=STATE_LONG,
        entry_regime=STATE_LONG,
        data_gap=False,
    ) == STATE_LONG
    assert hybrid_target_v1(
        STATE_FLAT,
        cross_1m=None,
        cross_entry=STATE_SHORT,
        entry_regime=STATE_SHORT,
        data_gap=False,
    ) == STATE_SHORT


def test_entry_cross_can_carry_reversal_without_direct_reverse_order() -> None:
    # Strategic target becomes the opposite side; the shared execution-request
    # mapper still turns observed LONG -> desired SHORT into CLOSE first.
    assert hybrid_target_v1(
        STATE_LONG,
        cross_1m=STATE_SHORT,
        cross_entry=STATE_SHORT,
        entry_regime=STATE_SHORT,
        data_gap=False,
    ) == STATE_SHORT


def test_gap_never_invents_hybrid_transition() -> None:
    assert hybrid_target_v1(
        STATE_LONG,
        cross_1m=STATE_SHORT,
        cross_entry=STATE_SHORT,
        entry_regime=STATE_SHORT,
        data_gap=True,
    ) == STATE_LONG


def test_both_hybrids_are_explicit_live_catalog_strategies() -> None:
    live_keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert set(HYBRID_STRATEGY_KEYS_V1.values()) <= live_keys
    assert hybrid_entry_timeframe_for_strategy_v1(HYBRID_STRATEGY_KEYS_V1[2]) == 2
    assert hybrid_entry_timeframe_for_strategy_v1(HYBRID_STRATEGY_KEYS_V1[5]) == 5
    assert hybrid_strategy_label_v1(2) == "MACD hybrid · exit 1m / entry 2m"
