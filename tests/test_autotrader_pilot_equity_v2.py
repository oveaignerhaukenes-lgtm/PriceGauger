from datetime import datetime, timedelta, timezone

import pytest

from autotrader_live_pilot_runtime_v2 import LivePilotPlanningStateV2
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_macd_flip_policy_v2 import macd_flip_intent_from_pair_v2
from autotrader_pilot_equity_v2 import (
    PilotEquitySnapshotV2,
    pilot_equity_snapshot_v2,
    refresh_pending_reversal_budget_v2,
)


T0 = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)


def obs(at, macd, signal):
    return MacdObservationV2(bar_time=at, macd=macd, signal=signal)


def pending_short(budget_amount=500.0):
    intent = macd_flip_intent_from_pair_v2(
        market_id=7,
        market_name="Australia Tech",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        target_fraction=1.0,
        budget_amount=budget_amount,
        budget_currency="NOK",
    )
    assert intent is not None
    return intent


def test_seed_plus_realized_profit_compounds_next_entry_budget():
    equity = pilot_equity_snapshot_v2(
        pilot_key="pilot-1",
        seed_capital=500.0,
        realized_net_pnl_entries=(1000.0,),
        currency="NOK",
    )
    assert equity.seed_capital == pytest.approx(500.0)
    assert equity.realized_net_pnl == pytest.approx(1000.0)
    assert equity.equity == pytest.approx(1500.0)
    assert equity.entry_budget == pytest.approx(1500.0)


def test_realized_losses_reduce_compounding_capital_too():
    equity = pilot_equity_snapshot_v2(
        pilot_key="pilot-1",
        seed_capital=500.0,
        realized_net_pnl_entries=(100.0, -250.0),
    )
    assert equity.realized_net_pnl == pytest.approx(-150.0)
    assert equity.entry_budget == pytest.approx(350.0)


def test_pilot_never_opens_from_negative_or_exhausted_equity():
    equity = pilot_equity_snapshot_v2(
        pilot_key="pilot-1",
        seed_capital=500.0,
        realized_net_pnl_entries=(-600.0,),
    )
    assert equity.equity == pytest.approx(-100.0)
    assert equity.entry_budget == 0.0


def test_pending_reversal_uses_newly_settled_profit_without_changing_signal_identity():
    pending = pending_short(500.0)
    state = LivePilotPlanningStateV2(
        last_evaluated_bar_time=T1,
        reversal_pending=True,
        pending_intent=pending,
    )
    equity = PilotEquitySnapshotV2(
        pilot_key="pilot-1",
        currency="NOK",
        seed_capital=500.0,
        realized_net_pnl=1000.0,
    )

    refreshed = refresh_pending_reversal_budget_v2(state=state, equity=equity)

    assert refreshed.pending_intent is not None
    assert refreshed.pending_intent.event_id == pending.event_id
    assert refreshed.pending_intent.signal_at == pending.signal_at
    assert refreshed.pending_intent.target_direction == pending.target_direction
    assert refreshed.pending_intent.budget_amount == pytest.approx(1500.0)
    assert refreshed.pending_intent.budget_currency == "NOK"


def test_pending_reversal_refuses_reopen_when_pilot_equity_is_exhausted():
    state = LivePilotPlanningStateV2(
        last_evaluated_bar_time=T1,
        reversal_pending=True,
        pending_intent=pending_short(),
    )
    equity = PilotEquitySnapshotV2(
        pilot_key="pilot-1",
        currency="NOK",
        seed_capital=500.0,
        realized_net_pnl=-500.0,
    )
    with pytest.raises(ValueError, match="equity is exhausted"):
        refresh_pending_reversal_budget_v2(state=state, equity=equity)
