from __future__ import annotations

from pathlib import Path

from autotrader_macd_intrabar_clock_v1 import LIVE_INTRABAR_MACD_TIMEFRAMES_V1
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


def test_all_simple_live_macd_controls_share_intrabar_clock() -> None:
    assert LIVE_MACD_CONTROL_TIMEFRAMES_V1 == (1, 2, 5, 15, 30)
    assert LIVE_INTRABAR_MACD_TIMEFRAMES_V1 == (1, 2, 5, 15, 30)
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


def test_all_simple_controls_use_persisted_forming_candle_clock() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    intrabar = Path("autotrader_macd_intrabar_clock_v1.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "live_macd_intrabar_clock_v1(" in runtime
    assert "MACD_1M_FLIP_STRATEGY_V2" in dispatch
    assert "MACD_FLIP_STRATEGY_V2" in dispatch
    assert "TIMEFRAME_MACD_LIVE_STRATEGIES" in dispatch
    assert "FAST_LIVE_STRATEGIES = {STRONG_COCKTAIL_STRATEGY_V2}" in dispatch
    assert "FormingCandleStore" in intrabar
    assert "realtime_forming_candles_1m" not in runtime
    assert "pg_v2_autotrader_macd_live_probe_state" in intrabar
    assert "float(current.spread) > 0.0" in intrabar
    assert "target_direction = DIRECTION_LONG" in intrabar
    assert "float(current.spread) < 0.0" in intrabar
    assert "target_direction = DIRECTION_SHORT" in intrabar
    assert "previous_spread <= 0.0 < current.spread" not in intrabar
    assert "previous_spread >= 0.0 > current.spread" not in intrabar


def test_intrabar_clock_uses_shared_provisional_close_macd_materializer() -> None:
    intrabar = Path("autotrader_macd_intrabar_clock_v1.py").read_text(encoding="utf-8")
    shared = Path("hypervigilant_macd_v1.py").read_text(encoding="utf-8")
    assert "materialize_hypervigilant_macd_v1(" in intrabar
    assert "tuple(item.point for item in bars)" in intrabar
    assert "forming_bar_time=candle.bar_time" in intrabar
    assert "forming_close=float(candle.close)" in intrabar
    assert "completed_before_current" in shared
    assert "current = ChartBar(" in shared
    assert "close=price" in shared
    assert "completed_before_current + (current,)" in shared


def test_intrabar_clock_is_fail_closed_on_stale_delayed_or_wrong_product_data() -> None:
    intrabar = Path("autotrader_macd_intrabar_clock_v1.py").read_text(encoding="utf-8")
    assert 'status.state).upper() != "STREAMING"' in intrabar
    assert "delayed_by_minutes" in intrabar
    assert "LIVE_INTRABAR_MAX_EVENT_AGE_SECONDS_V1" in intrabar
    assert "forming candle product mismatch" in intrabar
    assert "LIVE_INTRABAR_MAX_PROBE_GAP_SECONDS_V1" in intrabar


def test_binary_macd_retries_only_known_terminal_requests_through_normal_lifecycle() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "_rearm_retryable_terminal_request_v1" in runtime
    assert "status IN ('BLOCKED', 'REJECTED')" in runtime
    assert "SET status = 'PENDING'" in runtime
    assert "PENDING_TRANSITION_RETRY_READY" in runtime
    assert "SUPERSEDED, SUBMITTING, ORDER_ACCEPTED or UNCERTAIN" in runtime
    assert "trade/v2/orders" not in runtime


def test_binary_macd_request_created_flag_is_not_true_for_idempotent_conflict() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "existed_before = _matching_intent_request_exists_v1" in runtime
    assert "nominal_created and not existed_before" in runtime


def test_dispatch_uses_shared_request_lifecycle_and_runtime_has_no_order_authority() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    intrabar = Path("autotrader_macd_intrabar_clock_v1.py").read_text(encoding="utf-8")
    assert "TIMEFRAME_MACD_LIVE_STRATEGIES" in dispatch
    assert "run_macd_timeframe_live_once_v1" in dispatch
    assert "_persist_intent_and_request_v2" in runtime
    assert "place_order(" not in runtime
    assert "trade/v2/orders" not in runtime
    assert "place_order(" not in intrabar
    assert "trade/v2/orders" not in intrabar
