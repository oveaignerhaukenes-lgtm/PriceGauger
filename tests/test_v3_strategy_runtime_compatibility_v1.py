from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING
from autotrader_v3_macd_stoch_v1 import STRATEGY_KEY_V3 as STOCH
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3


def _obs():
    return MacdObservationV2(bar_time=datetime(2026,10,1,tzinfo=timezone.utc),macd=1.0,signal=0.0)


def _bars():
    return tuple(SimpleNamespace(high=101.0+i,low=99.0+i,close=100.0+i) for i in range(25))


@pytest.mark.parametrize("key", [HISTOGRAM, TRAILING, STOCH])
def test_every_registered_live_v3_strategy_accepts_runtime_contract(tmp_path,key):
    result=evaluate_strategy_bar_v3(
        strategy_key=key,trader_id="compat-"+key,
        observation=_obs(),bars=_bars(),db_path=str(tmp_path/"pg.db"))
    assert result.decision is not None


def test_registry_live_routes_are_exactly_runtime_compatible(tmp_path):
    for key, adapter in STRATEGIES_V3.items():
        if adapter.live_route_enabled:
            evaluate_strategy_bar_v3(
                strategy_key=key,trader_id="live-"+key,
                observation=_obs(),bars=_bars(),db_path=str(tmp_path/"pg.db"))
