from __future__ import annotations

from pathlib import Path

from autotrader_macd_timeframe_controls_v1 import macd_control_strategy_key_v1
from autotrader_macd_timeframe_live_v1 import (
    LIVE_MACD_CONTROL_STRATEGIES_V1,
    LIVE_MACD_CONTROL_TIMEFRAMES_V1,
    live_macd_control_timeframe_v1,
)
from autotrader_strategy_catalog_v2 import (
    MACD_2M_FLIP_STRATEGY_V2,
    MACD_5M_FLIP_STRATEGY_V2,
    MACD_15M_FLIP_STRATEGY_V2,
    strategy_spec_v2,
)


def test_2m_5m_and_15m_shadow_keys_are_the_same_keys_exposed_live() -> None:
    assert LIVE_MACD_CONTROL_TIMEFRAMES_V1 == (2, 5, 15)
    assert MACD_2M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(2)
    assert MACD_5M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(5)
    assert MACD_15M_FLIP_STRATEGY_V2 == macd_control_strategy_key_v1(15)
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_2M_FLIP_STRATEGY_V2] == 2
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_5M_FLIP_STRATEGY_V2] == 5
    assert LIVE_MACD_CONTROL_STRATEGIES_V1[MACD_15M_FLIP_STRATEGY_V2] == 15
    assert live_macd_control_timeframe_v1(MACD_2M_FLIP_STRATEGY_V2) == 2
    assert live_macd_control_timeframe_v1(MACD_5M_FLIP_STRATEGY_V2) == 5
    assert live_macd_control_timeframe_v1(MACD_15M_FLIP_STRATEGY_V2) == 15


def test_catalog_exposes_all_three_as_symmetric_long_short_live_choices() -> None:
    two = strategy_spec_v2(MACD_2M_FLIP_STRATEGY_V2)
    five = strategy_spec_v2(MACD_5M_FLIP_STRATEGY_V2)
    fifteen = strategy_spec_v2(MACD_15M_FLIP_STRATEGY_V2)
    assert two.label == "2m MACD flip · long/short"
    assert five.label == "5m MACD flip · long/short"
    assert fifteen.label == "15m MACD flip · long/short"
    assert two.can_long and two.can_short
    assert five.can_long and five.can_short
    assert fifteen.can_long and fifteen.can_short


def test_dispatch_uses_shared_request_lifecycle_and_runtime_has_no_order_authority() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    assert "TIMEFRAME_MACD_LIVE_STRATEGIES" in dispatch
    assert "run_macd_timeframe_live_once_v1" in dispatch
    assert "_persist_intent_and_request_v2" in runtime
    assert "place_order(" not in runtime
    assert "trade/v2/orders" not in runtime
