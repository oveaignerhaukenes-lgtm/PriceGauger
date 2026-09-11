from __future__ import annotations

from pathlib import Path

from autotrader_macd_timeframe_controls_v1 import macd_control_strategy_key_v1
from autotrader_macd_timeframe_live_v1 import (
    LIVE_MACD_CONTROL_STRATEGIES_V1,
    LIVE_MACD_CONTROL_TIMEFRAMES_V1,
    live_macd_control_timeframe_v1,
)
from autotrader_strategy_catalog_v2 import (
    MACD_1M_FLIP_STRATEGY_V2,
    MACD_2M_FLIP_STRATEGY_V2,
    MACD_5M_FLIP_STRATEGY_V2,
    MACD_15M_FLIP_STRATEGY_V2,
    MACD_FLIP_STRATEGY_V2,
    strategy_spec_v2,
)


def test_all_simple_live_macd_controls_have_expected_timeframes() -> None:
    assert LIVE_MACD_CONTROL_TIMEFRAMES_V1 == (1, 2, 5, 15, 30)
    assert MACD_2M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(2)
    assert MACD_5M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(5)
    assert MACD_15M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(15)
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_1M_FLIP_STRATEGY_V2] == 1
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_2M_FLIP_STRATEGY_V2] == 2
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_5M_FLIP_STRATEGY_V2] == 5
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_15M_FLIP_STRATEGY_V2] == 15
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_FLIP_STRATEGY_V2] == 30
    assert live_macd_control_timeframe_v1(MACD_1M_FLIP_STRATEGY_V2) == 1
    assert live_macd_control_timeframe_v1(MACD_2M_FLIP_STRATEGY_V2) == 2
    assert live_macd_control_timeframe_v1(MACD_5M_FLIP_STRATEGY_V2) == 5
    assert live_macd_control_timeframe_v1(MACD_15M_FLIP_STRATEGY_V2) == 15
    assert live_macd_control_timeframe_v1(MACD_FLIP_STRATEGY_V2) == 30


def test_catalog_exposes_all_five_as_symmetric_long_short_live_choices() -> None:
    one = strategy_spec_v2(MACD_1M_FLIP_STRATEGY_V2)
    two = strategy_spec_v2(MACD_2M_FLIP_STRATEGY_V2)
    five = strategy_spec_v2(MACD_5M_FLIP_STRATEGY_V2)
    fifteen = strategy_spec_v2(MACD_15M_FLIP_STRATEGY_V2)
    thirty = strategy_spec_v2(MACD_FLIP_STRATEGY_V2)
    assert one.label == "MACD1"
    assert two.label == "MACD2"
    assert five.label == "MACD5"
    assert fifteen.label == "MACD15"
    assert thirty.label == "MACD30"
    assert one.can_long and one.can_short
    assert two.can_long and two.can_short
    assert five.can_long and five.can_short
    assert fifteen.can_long and fifteen.can_short
    assert thirty.can_long and thirty.can_short


def test_simple_controls_use_completed_timeframe_bars_not_forming_candles() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "_timeframe_clock_v1(tuple(bars), timeframe_minutes=minutes)" in runtime
    assert "closed_bars_v2(" in runtime
    assert "macd_observations_v2(" in runtime
    assert "live_macd_intrabar_clock_v1(" not in runtime
    assert "forming candle" not in runtime.lower()
    assert "CLOSED_CROSS_" in runtime
    assert "TIMEFRAME_MACD_LIVE_STRATEGIES" in dispatch


def test_closed_bar_clock_only_emits_true_completed_bar_crosses() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "previous.spread <= 0.0 < current.spread" in runtime
    assert "previous.spread >= 0.0 > current.spread" in runtime
    assert "clock.action_at > state.last_action_at" in runtime
    assert "completed timeframe bars" in runtime


def test_binary_macd_retries_only_known_terminal_requests_through_normal_lifecycle() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "_rearm_retryable_terminal_request_v1" in runtime
    assert "status IN ('BLOCKED', 'REJECTED')" in runtime
    assert "SET status = 'PENDING'" in runtime
    assert "PENDING_TRANSITION_RETRY_READY" in runtime
    assert "trade/v2/orders" not in runtime


def test_binary_macd_request_created_flag_is_not_true_for_idempotent_conflict() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "existed_before = _matching_intent_request_exists_v1" in runtime
    assert "nominal_created and not existed_before" in runtime


def test_dispatch_uses_shared_request_lifecycle_and_runtime_has_no_order_authority() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "TIMEFRAME_MACD_LIVE_STRATEGIES" in dispatch
    assert "run_macd_timeframe_live_once_v1" in dispatch
    assert "_persist_intent_and_request_v2" in runtime
    assert "place_order(" not in runtime
    assert "trade/v2/orders" not in runtime
