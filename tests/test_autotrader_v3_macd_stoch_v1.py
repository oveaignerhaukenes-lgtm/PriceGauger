from datetime import datetime, timezone
from types import SimpleNamespace

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v1 import macd_stoch_target_v3, stochastic_kd_v3
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3


def _bars(closes):
    return tuple(SimpleNamespace(high=float(x)+1, low=float(x)-1, close=float(x)) for x in closes)


def _obs(spread):
    return MacdObservationV2(
        bar_time=datetime(2026, 10, 1, tzinfo=timezone.utc),
        macd=float(spread),
        signal=0.0,
    )


def test_macd_stoch_is_live_registered():
    assert STRATEGIES_V3["macd-stoch-v1"].live_route_enabled is True


def test_bearish_stoch_rollover_flattens_long_without_reversing():
    # Search a deterministic close sequence whose final sample crosses K below D.
    prefix = [100 + i * 0.5 for i in range(18)]
    found = None
    for a in range(108, 116):
        for b in range(100, 114):
            bars = _bars(prefix + [a, b])
            kd = stochastic_kd_v3(bars)
            if kd and kd[0] >= kd[1] and kd[2] < kd[3]:
                found = bars
                break
        if found:
            break
    assert found is not None

    decision = macd_stoch_target_v3(
        current_target=TargetInventoryV3(0.06),
        observation=_obs(2.0),
        previous_observation=_obs(1.0),
        bars=found,
    )
    assert decision.action == "STOCH_FLAT_LONG"
    assert decision.target.amount == 0.0


def test_stoch_never_creates_opposite_position_from_flat():
    closes = [100 + i * 0.3 for i in range(25)]
    decision = macd_stoch_target_v3(
        current_target=TargetInventoryV3(0.0),
        observation=_obs(1.0),
        previous_observation=_obs(0.5),
        bars=_bars(closes),
    )
    assert decision.target.amount >= 0.0
