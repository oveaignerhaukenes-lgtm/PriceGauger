from pathlib import Path
import pytest

from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM_KEY
from autotrader_v3_macd_histogram_flip_build_v1 import STRATEGY_KEY_V3 as HISTOGRAM_FLIP_BUILD_KEY
from autotrader_v3_macd_histogram_peak_flip_v1 import STRATEGY_KEY_V3 as PEAK_FLIP_KEY
from autotrader_v3_macd_flip_v1 import STRATEGY_KEY_V3 as FLIP_KEY
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_macd_stoch_v1 import STRATEGY_KEY_V3 as STOCH_KEY
from autotrader_v3_macd_stoch_v2 import STRATEGY_KEY_V3 as STOCH_V2_KEY
from autotrader_v3_macd_stoch_v21 import STRATEGY_KEY_V3 as STOCH_V21_KEY
from autotrader_v3_avoid_loss_strategy_v1 import STRATEGY_KEY_V3 as AVOID_LOSS_KEY
from autotrader_v3_vwap_regime_histogram_v1 import STRATEGY_KEY_V3 as VWAP_REGIME_KEY
from autotrader_v3_macd_regime_histogram_v1 import STRATEGY_KEY_V3 as MACD_REGIME_HIST_KEY
from autotrader_v3_aen2_sticky_regime_v1 import STRATEGY_KEY_V3 as AEN2_STICKY_KEY
from autotrader_v3_aen21_sticky_fast_exit_v1 import STRATEGY_KEY_V3 as AEN21_FAST_EXIT_KEY
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, strategy_adapter_v3
from autotrader_v3_aen_core_bridge_v1 import AEN_CORE_KEYS_V3, evaluate_aen_core_v3


def test_v3_registry_routes_all_strategies_through_same_decision_contract():
    assert set(STRATEGIES_V3) == {HISTOGRAM_KEY, HISTOGRAM_FLIP_BUILD_KEY, PEAK_FLIP_KEY, VWAP_REGIME_KEY, MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY, TRAILING_KEY, FLIP_KEY, STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY, AVOID_LOSS_KEY} | AEN_CORE_KEYS_V3
    driver = strategy_adapter_v3(HISTOGRAM_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(HISTOGRAM_FLIP_BUILD_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(PEAK_FLIP_KEY).evaluate_closed_bar
    assert strategy_adapter_v3(PEAK_FLIP_KEY).live_route_enabled is True
    assert driver is strategy_adapter_v3(VWAP_REGIME_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(MACD_REGIME_HIST_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(AEN2_STICKY_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(AEN21_FAST_EXIT_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(TRAILING_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(FLIP_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(STOCH_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(STOCH_V2_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(STOCH_V21_KEY).evaluate_closed_bar
    assert driver is strategy_adapter_v3(AVOID_LOSS_KEY).evaluate_closed_bar
    assert strategy_adapter_v3(STOCH_V21_KEY).live_route_enabled
    for key in AEN_CORE_KEYS_V3:
        assert strategy_adapter_v3(key).evaluate_closed_bar is evaluate_aen_core_v3
        assert strategy_adapter_v3(key).live_route_enabled is True


def test_trailing_live_route_uses_explicit_open_add_policy():
    assert strategy_adapter_v3(TRAILING_KEY).live_route_enabled is True
    runtime = Path('autotrader_v3_live_runtime_v1.py').read_text(encoding='utf-8')
    assert "mutation.action in {'OPEN','ADD'}" in runtime
    assert 'load_execution_policy_v3' in runtime
    with pytest.raises(ValueError, match="Unregistered"):
        strategy_adapter_v3("unknown-strategy")


def test_runtime_uses_registry_and_never_substitutes_histogram_for_trailing():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "STRATEGIES_V3.get(e.strategy_key)" in source
    assert "evaluate_strategy_bar_v3(" in source
    assert "adapter.live_route_enabled" in source
    assert "e.strategy_key==STRATEGY_KEY_V3" not in source


def test_v2_timeframe_strategy_does_not_show_fast_runtime_false_alarm():
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert "MACD/tidsperiode-strategier kjøres i egen runtime" in source
    assert "LIVE runtime: ingen persistert strategi-evaluering ennå." not in source
