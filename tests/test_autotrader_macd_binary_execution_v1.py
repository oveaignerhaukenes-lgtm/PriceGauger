from __future__ import annotations

from pathlib import Path

from autotrader_entry_sizing_policy_v2 import SIZING_MODE_MAX
from autotrader_macd_binary_execution_v1 import (
    SIMPLE_BINARY_MACD_STRATEGIES_V1,
    is_simple_binary_macd_strategy_v1,
)


def test_simple_binary_macd_strategy_set_is_exact() -> None:
    assert SIMPLE_BINARY_MACD_STRATEGIES_V1 == {
        "macd-1m-flip-control-shadow-v1",
        "macd-2m-flip-control-shadow-v1",
        "macd-5m-flip-control-shadow-v1",
        "macd-15m-flip-control-shadow-v1",
        "macd-30m-long-short-v1",
        "macd2-10-v1",
        "macd2-s-v1",
        "macd-a-v1",
    }
    assert is_simple_binary_macd_strategy_v1("macd-5m-flip-control-shadow-v1")
    assert is_simple_binary_macd_strategy_v1("macd-30m-long-short-v1")
    assert is_simple_binary_macd_strategy_v1("macd2-s-v1")
    assert not is_simple_binary_macd_strategy_v1("strong-cocktail-shadow-v1")


def test_simple_macd_runtime_forces_max_within_pilot() -> None:
    helper = Path("autotrader_macd_binary_execution_v1.py").read_text(encoding="utf-8")
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    model_runtime = Path("autotrader_macd_models_live_v1.py").read_text(encoding="utf-8")
    assert SIZING_MODE_MAX == "MAX_WITHIN_PILOT"
    assert "ensure_binary_macd_max_sizing_v1(enrollment, client)" in runtime
    assert "ensure_binary_macd_max_sizing_v1(enrollment, client)" in model_runtime
    assert 'for direction in ("LONG", "SHORT")' in helper
    assert "sizing_mode=SIZING_MODE_MAX" in helper


def test_binary_reversal_closes_current_full_net_before_open() -> None:
    close = Path("autotrader_strategy_live_close_v2.py").read_text(encoding="utf-8")
    open_runtime = Path("autotrader_live_open_legacy_v2.py").read_text(encoding="utf-8")
    assert "_binary_macd_rebase_is_safe" in close
    assert "observation=current" in close
    assert "current.amount" in close
    assert 'block_reason="PRODUCT_NOT_CONFIRMED_FLAT"' in open_runtime
    assert "IsForceOpen" not in close


def test_binary_contract_keeps_broker_flat_confirmation_as_execution_safety() -> None:
    runtime = Path("autotrader_macd_timeframe_live_v1.py").read_text(encoding="utf-8")
    model_runtime = Path("autotrader_macd_models_live_v1.py").read_text(encoding="utf-8")
    assert "CLOSE -> broker-confirmed FLAT -> OPEN" in runtime
    assert "MAX_WITHIN_PILOT" in runtime
    assert "trade/v2/orders" not in model_runtime
