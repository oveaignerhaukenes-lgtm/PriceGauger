from __future__ import annotations

from datetime import datetime, timezone

import autotrader_macd_dry_run_v2 as strategy
from trading_desk import ChartBar


def _obs(stamp: str, macd: float, signal: float) -> strategy.MacdObservationV2:
    return strategy.MacdObservationV2(
        bar_time=datetime.fromisoformat(stamp.replace("Z", "+00:00")),
        macd=macd,
        signal=signal,
    )


def test_closed_30m_bars_exclude_forming_bucket() -> None:
    points = []
    for minute in range(30):
        points.append((f"2026-08-16T10:{minute:02d}:00Z", 100.0 + minute))
    # A single observation exists in the next bucket. That 10:30 bucket is still
    # forming and must never participate in an AutoTrader signal.
    points.append(("2026-08-16T10:30:00Z", 150.0))

    bars = strategy.closed_30m_bars_v2(points, market="Gold")

    assert len(bars) == 1
    assert bars[0].bar_time.startswith("2026-08-16T10:00:00")
    assert bars[0].close == 129.0


def test_closed_30m_bar_becomes_eligible_after_final_minute() -> None:
    points = [
        (f"2026-08-16T10:{minute:02d}:00Z", 100.0 + minute)
        for minute in range(60)
    ]

    bars = strategy.closed_30m_bars_v2(points, market="Gold")

    assert [bar.close for bar in bars] == [129.0, 159.0]


def test_cross_semantics_are_exact_and_directional() -> None:
    down_or_equal = _obs("2026-08-16T10:00:00Z", 1.0, 1.0)
    above = _obs("2026-08-16T10:30:00Z", 1.2, 1.0)
    below = _obs("2026-08-16T11:00:00Z", 0.8, 1.0)

    assert strategy._cross(down_or_equal, above) == strategy.SIGNAL_UP
    assert strategy._cross(above, below) == strategy.SIGNAL_DOWN
    assert strategy._cross(below, below) is None


def test_long_flat_transition_never_creates_short_state() -> None:
    previous = _obs("2026-08-16T10:00:00Z", 0.8, 1.0)
    current = _obs("2026-08-16T10:30:00Z", 1.2, 1.0)
    enter = strategy._transition_for_signal(
        market_id=7,
        market_name="Gold",
        signal=strategy.SIGNAL_UP,
        previous=previous,
        current=current,
        prior_state=strategy.POSITION_FLAT,
    )
    assert enter.action == strategy.ACTION_BUY
    assert enter.desired_state == strategy.POSITION_LONG

    exit_previous = current
    exit_current = _obs("2026-08-16T11:00:00Z", 0.8, 1.0)
    exit_transition = strategy._transition_for_signal(
        market_id=7,
        market_name="Gold",
        signal=strategy.SIGNAL_DOWN,
        previous=exit_previous,
        current=exit_current,
        prior_state=strategy.POSITION_LONG,
    )
    assert exit_transition.action == strategy.ACTION_SELL_ALL
    assert exit_transition.desired_state == strategy.POSITION_FLAT
    assert "SHORT" not in {enter.desired_state, exit_transition.desired_state}


def test_same_signal_event_has_restart_stable_identity() -> None:
    previous = _obs("2026-08-16T10:00:00Z", 0.8, 1.0)
    current = _obs("2026-08-16T10:30:00Z", 1.2, 1.0)
    first = strategy._transition_for_signal(
        market_id=7,
        market_name="Gold",
        signal=strategy.SIGNAL_UP,
        previous=previous,
        current=current,
        prior_state=strategy.POSITION_FLAT,
    )
    second = strategy._transition_for_signal(
        market_id=7,
        market_name="Gold",
        signal=strategy.SIGNAL_UP,
        previous=previous,
        current=current,
        prior_state=strategy.POSITION_FLAT,
    )
    assert first.event_id == second.event_id


def test_already_evaluated_closed_bar_is_not_replayed(monkeypatch) -> None:
    previous = _obs("2026-08-16T10:00:00Z", 0.8, 1.0)
    current = _obs("2026-08-16T10:30:00Z", 1.2, 1.0)
    monkeypatch.setattr(strategy, "closed_30m_bars_v2", lambda points, market: (ChartBar(market, "x", 1, 1, 1, 1),))
    monkeypatch.setattr(strategy, "macd_observations_v2", lambda bars: (previous, current))
    monkeypatch.setattr(
        strategy,
        "load_dry_run_state_v2",
        lambda **kwargs: strategy.DryRunStateV2(
            market_id=7,
            market_name="Gold",
            position_state=strategy.POSITION_LONG,
            last_evaluated_bar_time=current.bar_time,
            last_signal_bar_time=current.bar_time,
        ),
    )
    calls = []
    monkeypatch.setattr(strategy, "_persist_progress_v2", lambda **kwargs: calls.append(kwargs))

    state, transitions = strategy.evaluate_macd_long_flat_points_v2(
        market_id=7,
        market_name="Gold",
        points=(("2026-08-16T10:00:00Z", 1.0),),
    )

    assert state.position_state == strategy.POSITION_LONG
    assert transitions == ()
    assert calls == []


def test_strategy_module_is_dry_run_only() -> None:
    source = open("autotrader_macd_dry_run_v2.py", encoding="utf-8").read()
    assert "place_order(" not in source
    assert ".precheck(" not in source
    assert "execute_confirmed_manual_order" not in source
    assert strategy.ACTION_BUY == "WOULD_BUY"
    assert strategy.ACTION_SELL_ALL == "WOULD_SELL_ALL"
