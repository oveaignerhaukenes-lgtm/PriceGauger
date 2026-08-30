from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autotrader_macd_dry_run_v2 import SIGNAL_DOWN, SIGNAL_UP, MacdObservationV2
from autotrader_shadow_benchmark_v2 import (
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    apply_shadow_return_v2,
    replay_shadow_benchmark_v2,
    target_state_for_signal_v2,
)
from autotrader_strategy_catalog_v2 import (
    MACD_FLIP_STRATEGY_V2,
    MACD_LONG_FLAT_STRATEGY_V2,
    MACD_SHORT_FLAT_STRATEGY_V2,
)


def _obs(hour: int, minute: int, spread: float) -> MacdObservationV2:
    return MacdObservationV2(
        bar_time=datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc),
        macd=spread,
        signal=0.0,
    )


def test_all_three_strategy_signal_policies_are_symmetric():
    assert target_state_for_signal_v2(MACD_LONG_FLAT_STRATEGY_V2, SIGNAL_UP) == STATE_LONG
    assert target_state_for_signal_v2(MACD_LONG_FLAT_STRATEGY_V2, SIGNAL_DOWN) == STATE_FLAT

    assert target_state_for_signal_v2(MACD_SHORT_FLAT_STRATEGY_V2, SIGNAL_UP) == STATE_FLAT
    assert target_state_for_signal_v2(MACD_SHORT_FLAT_STRATEGY_V2, SIGNAL_DOWN) == STATE_SHORT

    assert target_state_for_signal_v2(MACD_FLIP_STRATEGY_V2, SIGNAL_UP) == STATE_LONG
    assert target_state_for_signal_v2(MACD_FLIP_STRATEGY_V2, SIGNAL_DOWN) == STATE_SHORT


def test_shadow_return_uses_signed_exposure_and_never_invents_credit():
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_LONG, price_return=0.10) == pytest.approx(550.0)
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_SHORT, price_return=0.10) == pytest.approx(450.0)
    assert apply_shadow_return_v2(equity=500.0, position_state=STATE_FLAT, price_return=0.10) == pytest.approx(500.0)
    assert apply_shadow_return_v2(equity=100.0, position_state=STATE_LONG, price_return=-2.0) == 0.0


def test_bootstrap_keeps_observed_starting_exposure_instead_of_replaying_macd_regime():
    observations = (
        _obs(9, 30, -1.0),
        _obs(10, 0, -0.8),
        _obs(10, 30, -0.6),
    )
    close_by_time = {
        observations[0].bar_time: 120.0,
        observations[1].bar_time: 100.0,
        observations[2].bar_time: 90.0,
    }
    # Enrollment occurs inside the 10:00-10:30 bar while MACD is already bearish.
    # The benchmark must still begin LONG because that is the observed exposure.
    result = replay_shadow_benchmark_v2(
        strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        seed_equity=100.0,
        initial_state=STATE_LONG,
        started_at=datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc),
        observations=observations,
        close_by_time=close_by_time,
    )
    assert result.evaluated_bars == 2
    assert result.position_state == STATE_LONG
    assert result.transitions == 0
    # First post-enrollment closed bar is the price baseline; only 100 -> 90 counts.
    assert result.equity == pytest.approx(90.0)


def test_first_cross_confirmed_after_enrollment_can_change_state_without_prestart_return():
    observations = (
        _obs(9, 30, -1.0),
        _obs(10, 0, 1.0),
    )
    close_by_time = {
        observations[0].bar_time: 50.0,
        observations[1].bar_time: 100.0,
    }
    started_at = datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc)

    long_flat = replay_shadow_benchmark_v2(
        strategy_key=MACD_LONG_FLAT_STRATEGY_V2,
        seed_equity=100.0,
        initial_state=STATE_SHORT,
        started_at=started_at,
        observations=observations,
        close_by_time=close_by_time,
    )
    short_flat = replay_shadow_benchmark_v2(
        strategy_key=MACD_SHORT_FLAT_STRATEGY_V2,
        seed_equity=100.0,
        initial_state=STATE_SHORT,
        started_at=started_at,
        observations=observations,
        close_by_time=close_by_time,
    )
    flip = replay_shadow_benchmark_v2(
        strategy_key=MACD_FLIP_STRATEGY_V2,
        seed_equity=100.0,
        initial_state=STATE_SHORT,
        started_at=started_at,
        observations=observations,
        close_by_time=close_by_time,
    )

    assert long_flat.position_state == STATE_LONG
    assert short_flat.position_state == STATE_FLAT
    assert flip.position_state == STATE_LONG
    assert long_flat.equity == short_flat.equity == flip.equity == pytest.approx(100.0)
    assert long_flat.transitions == short_flat.transitions == flip.transitions == 1


def test_shadow_benchmark_is_read_only_and_cannot_contaminate_authoritative_live_ledger():
    source = Path("autotrader_shadow_benchmark_v2.py").read_text(encoding="utf-8")
    assert "record_realized_net_pnl_v2" not in source
    assert "pg_v2_autotrader_pilot_equity_events" not in source
    assert "pg_v2_autotrader_live_open" not in source
    assert "pg_v2_autotrader_live_close" not in source
    assert "CREATE TABLE" not in source
    assert "session.post" not in source
    assert "_post_once" not in source
