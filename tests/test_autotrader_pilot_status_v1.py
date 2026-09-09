from __future__ import annotations

from autotrader_pilot_equity_v2 import pilot_equity_snapshot_v2
from autotrader_pilot_status_v1 import pilot_status_from_snapshot_v1


def test_pilot_status_compounds_seed_plus_realized_pnl() -> None:
    snapshot = pilot_equity_snapshot_v2(
        pilot_key="pilot-test",
        seed_capital=500.0,
        realized_net_pnl_entries=(50.0, -20.0, 70.0),
        currency="NOK",
    )
    status = pilot_status_from_snapshot_v1(
        snapshot,
        closed_trades=3,
        wins=2,
        losses=1,
        breakeven=0,
        last_open_amount=0.01,
        last_open_budget=600.0,
        last_open_initial_margin=594.0,
        last_open_notional=3000.0,
        last_open_status="RECONCILED",
    )

    assert status.seed_capital == 500.0
    assert status.realized_net_pnl == 100.0
    assert status.equity == 600.0
    assert status.return_pct == 20.0
    assert status.win_rate_pct == (2 / 3) * 100.0
    assert status.harvest_threshold == 1000.0
    assert status.capital_utilization_pct == 99.0


def test_harvest_threshold_is_double_original_seed_across_activation_cohorts() -> None:
    current_cohort = pilot_equity_snapshot_v2(
        pilot_key="pilot-activation-2",
        seed_capital=750.0,
        realized_net_pnl_entries=(250.0,),
        currency="NOK",
    )
    status = pilot_status_from_snapshot_v1(
        current_cohort,
        original_seed_capital=500.0,
        cohort_count=2,
        closed_trades=9,
        wins=6,
        losses=3,
        breakeven=0,
    )

    assert status.equity == 1000.0
    assert status.seed_capital == 500.0
    assert status.realized_net_pnl == 500.0
    assert status.harvest_threshold == 1000.0
    assert status.cohort_count == 2


def test_unresolved_trade_set_has_no_win_rate_or_utilization() -> None:
    snapshot = pilot_equity_snapshot_v2(
        pilot_key="pilot-test",
        seed_capital=500.0,
        currency="NOK",
    )
    status = pilot_status_from_snapshot_v1(
        snapshot,
        closed_trades=0,
        wins=0,
        losses=0,
        breakeven=0,
    )

    assert status.win_rate_pct is None
    assert status.capital_utilization_pct is None
