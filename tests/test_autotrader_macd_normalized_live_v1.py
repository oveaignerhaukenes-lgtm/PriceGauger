from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from autotrader_macd_normalized_live_v1 import (
    MACD_NORMALIZED_LIVE_STRATEGIES_V1,
    NormalizedManagerLiveStateV1,
    _manager_state_from_observation_v1,
    _manager_step_v1,
)
from autotrader_strategy_catalog_v2 import (
    MACD_NORM_MANAGER_STRATEGY_V1,
    MACD_NORM_STRATEGY_V1,
    strategy_spec_v2,
)


def _state(*, direction: str, active_bars: int = 0, mfe: float = 0.0, cooldown: int = 0,
           blocked: str | None = None, reentry_count: int = 0) -> NormalizedManagerLiveStateV1:
    return NormalizedManagerLiveStateV1(
        pilot_key="pilot",
        strategy_key=MACD_NORM_MANAGER_STRATEGY_V1,
        direction=direction,
        active_bars=active_bars,
        mfe_pct=mfe,
        cooldown_remaining=cooldown,
        blocked_reentry_direction=blocked,
        reentry_count=reentry_count,
        last_action_at=datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc),
    )


def test_normalized_strategies_are_live_selectable() -> None:
    assert MACD_NORMALIZED_LIVE_STRATEGIES_V1 == {
        MACD_NORM_STRATEGY_V1,
        MACD_NORM_MANAGER_STRATEGY_V1,
    }
    assert strategy_spec_v2(MACD_NORM_STRATEGY_V1).label == "MACD norm"
    assert strategy_spec_v2(MACD_NORM_MANAGER_STRATEGY_V1).label == "MACD norm + manager"


def test_normalized_manager_requires_three_bar_reversal_confirmation() -> None:
    at = datetime(2026, 9, 16, 7, 1, tzinfo=timezone.utc)
    state = _state(direction="LONG", active_bars=10)
    held, reason = _manager_step_v1(
        state,
        raw_targets=("LONG", "SHORT", "SHORT"),
        current_pnl_pct=0.0,
        rolling_vol=0.001,
        action_at=at,
    )
    assert held.direction == "LONG"
    assert reason == "hold"

    reversed_state, reason = _manager_step_v1(
        held,
        raw_targets=("SHORT", "SHORT", "SHORT"),
        current_pnl_pct=0.0,
        rolling_vol=0.001,
        action_at=at,
    )
    assert reversed_state.direction == "SHORT"
    assert reason == "confirmed_reversal"


def test_normalized_manager_profit_lock_uses_actual_position_mfe() -> None:
    state = _state(direction="LONG", active_bars=4, mfe=0.0100)
    next_state, reason = _manager_step_v1(
        state,
        raw_targets=("LONG", "LONG", "LONG"),
        current_pnl_pct=0.0074,
        rolling_vol=0.001,
        action_at=datetime(2026, 9, 16, 7, 2, tzinfo=timezone.utc),
    )
    assert next_state.direction == "FLAT"
    assert next_state.blocked_reentry_direction == "LONG"
    assert next_state.cooldown_remaining == 3
    assert reason == "profit_lock"


def test_normalized_manager_reentry_waits_for_cooldown_and_confirmation() -> None:
    state = _state(direction="FLAT", cooldown=1, blocked="LONG")
    first, reason = _manager_step_v1(
        state,
        raw_targets=("LONG",),
        current_pnl_pct=0.0,
        rolling_vol=0.001,
        action_at=datetime(2026, 9, 16, 7, 3, tzinfo=timezone.utc),
    )
    assert first.direction == "FLAT"
    assert first.reentry_count == 1
    assert reason == "reentry_wait"

    second, reason = _manager_step_v1(
        first,
        raw_targets=("LONG",),
        current_pnl_pct=0.0,
        rolling_vol=0.001,
        action_at=datetime(2026, 9, 16, 7, 4, tzinfo=timezone.utc),
    )
    assert second.direction == "LONG"
    assert reason == "reentry"


def test_manager_handoff_initializes_mfe_from_real_saxo_position() -> None:
    enrollment = SimpleNamespace(
        pilot_key="pilot",
        strategy_key=MACD_NORM_MANAGER_STRATEGY_V1,
    )
    observation = SimpleNamespace(pnl_pct=1.25)
    state = _manager_state_from_observation_v1(
        enrollment,
        observed=observation,
        observed_direction="LONG",
        action_at=datetime(2026, 9, 16, 7, 5, tzinfo=timezone.utc),
    )
    assert state.direction == "LONG"
    assert state.mfe_pct == 0.0125
    assert state.active_bars == 0


def test_normalized_live_runtime_uses_common_execution_contract_only() -> None:
    runtime = Path("autotrader_macd_normalized_live_v1.py").read_text(encoding="utf-8").lower()
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    assert "_persist_intent_and_request_v2" in runtime
    assert "_persist_bootstrap_v2" in runtime
    assert "run_macd_normalized_live_once_v1" in dispatch
    assert "MACD_NORMALIZED_LIVE_STRATEGIES_V1" in dispatch
    for forbidden in ("place_order(", "trade/v2/orders", "client.post(", "requests.post("):
        assert forbidden not in runtime


def test_normalized_live_manager_cannot_delay_authoritative_cross() -> None:
    state = _state(direction="SHORT", active_bars=12, mfe=0.01, cooldown=3, blocked="LONG")
    next_state, reason = _manager_step_v1(
        state,
        raw_targets=("SHORT", "SHORT", "LONG"),
        current_pnl_pct=-0.002,
        rolling_vol=0.001,
        action_at=datetime(2026, 9, 16, 7, 6, tzinfo=timezone.utc),
        authoritative_cross="LONG",
    )
    assert next_state.direction == "LONG"
    assert next_state.cooldown_remaining == 0
    assert next_state.blocked_reentry_direction is None
    assert reason == "authoritative_cross"


def test_same_direction_authoritative_cross_preserves_live_manager_mfe() -> None:
    state = _state(direction="LONG", active_bars=7, mfe=0.012)
    next_state, reason = _manager_step_v1(
        state,
        raw_targets=("LONG", "LONG", "LONG"),
        current_pnl_pct=0.010,
        rolling_vol=0.001,
        action_at=datetime(2026, 9, 16, 7, 7, tzinfo=timezone.utc),
        authoritative_cross="LONG",
    )
    assert next_state.direction == "LONG"
    assert next_state.active_bars == 8
    assert next_state.mfe_pct == 0.012
    assert reason == "authoritative_cross_hold"


def test_normalized_live_evaluates_new_closed_bar_before_continuing_old_pending_intent() -> None:
    runtime = Path("autotrader_macd_normalized_live_v1.py").read_text(encoding="utf-8")
    assert "New closed-bar evidence is evaluated even while an older transition is pending." in runtime
    frame_pos = runtime.index("frame, replay_action_at, data_gap = _latest_normalized_frame_v1(eligible)")
    tail_pending_pos = runtime.rindex(
        "if state.pending_target_direction is not None and observed_direction != state.pending_target_direction:"
    )
    assert frame_pos < tail_pending_pos
    assert "supersede_prior=True" in runtime
