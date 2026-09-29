from pathlib import Path
import pytest

from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM_KEY
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, strategy_adapter_v3


def test_v3_registry_routes_both_strategies_through_same_decision_contract():
    assert set(STRATEGIES_V3) == {HISTOGRAM_KEY, TRAILING_KEY}
    assert strategy_adapter_v3(HISTOGRAM_KEY).evaluate_closed_bar is strategy_adapter_v3(TRAILING_KEY).evaluate_closed_bar


def test_trailing_remains_blocked_from_live_until_durable_execution_is_validated():
    assert strategy_adapter_v3(TRAILING_KEY).live_execution_validated is False
    with pytest.raises(ValueError, match="Unregistered"):
        strategy_adapter_v3("unknown-strategy")


def test_runtime_uses_registry_and_never_substitutes_histogram_for_trailing():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "STRATEGIES_V3.get(e.strategy_key)" in source
    assert "evaluate_strategy_bar_v3(" in source
    assert "adapter.live_execution_validated" in source
    assert "e.strategy_key==STRATEGY_KEY_V3" not in source


def test_v2_timeframe_strategy_does_not_show_fast_runtime_false_alarm():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "MACD/tidsperiode-strategier kjøres i egen runtime" in source
    assert "LIVE runtime: ingen persistert strategi-evaluering ennå." not in source
