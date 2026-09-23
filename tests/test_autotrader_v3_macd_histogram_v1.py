from datetime import datetime,timezone
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import *

def o(v): return MacdObservationV2(bar_time=datetime(2026,1,1,tzinfo=timezone.utc),macd=v,signal=0)

def test_histogram_direction_is_the_only_dynamic_rule():
    ds=replay_macd_histogram_v3([o(-5),o(-8),o(-10),o(-7),o(-3),o(2),o(5),o(3)],initial_target=TargetInventoryV3(0))
    assert [d.target.amount for d in ds]==[-.01,-.02,-.03,-.02,-.01,0,.01,0]

def test_histogram_turn_back_rebuilds_without_waiting_for_zero():
    ds=replay_macd_histogram_v3([o(-10),o(-6),o(-8)],initial_target=TargetInventoryV3(-.02))
    assert [d.target.amount for d in ds]==[-.03,-.02,-.03]
