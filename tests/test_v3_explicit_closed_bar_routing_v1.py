from datetime import datetime, timezone

import pytest
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING


def obs(minute, spread):
    return MacdObservationV2(
        bar_time=datetime(2026, 9, 29, 8, minute, tzinfo=timezone.utc),
        macd=spread, signal=0.0,
    )


def test_explicit_strategies_diverge_on_spread_reversal(tmp_path):
    db = str(tmp_path / "strategies.db")
    # Both enter LONG. On a falling but still-positive histogram, histogram
    # trails out, whereas trailing enforces its own MACD regime boundary.
    for key in (TRAILING, HISTOGRAM):
        a = evaluate_closed_bar_once_v3(trader_id=key, strategy_key=key, observation=obs(5, 1), db_path=db)
        b = evaluate_closed_bar_once_v3(trader_id=key, strategy_key=key, observation=obs(10, 0.5), db_path=db)
        assert a.is_new and a.decision.target.amount == 0.01
        assert b.is_new and b.decision.target.amount == 0
        dup = evaluate_closed_bar_once_v3(trader_id=key, strategy_key=key, observation=obs(10, 0.5), db_path=db)
        assert not dup.is_new and dup.decision.target.amount == 0


def test_trailing_regime_cross_flat_is_not_histogram_behavior(tmp_path):
    db = str(tmp_path / "reverse.db")
    for key in (TRAILING, HISTOGRAM):
        evaluate_closed_bar_once_v3(trader_id=key, strategy_key=key, observation=obs(5, 1), db_path=db)
    t = evaluate_closed_bar_once_v3(trader_id=TRAILING, strategy_key=TRAILING, observation=obs(10, -3), db_path=db)
    h = evaluate_closed_bar_once_v3(trader_id=HISTOGRAM, strategy_key=HISTOGRAM, observation=obs(10, -3), db_path=db)
    assert t.decision.action == "REGIME_CROSS_FLAT"
    assert h.decision.action == "REDUCE"


def test_unknown_strategy_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_closed_bar_once_v3(trader_id="t", strategy_key="unknown", observation=obs(5, 1), db_path=str(tmp_path/"x.db"))
