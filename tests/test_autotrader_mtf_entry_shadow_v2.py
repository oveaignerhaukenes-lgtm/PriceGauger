from __future__ import annotations

from datetime import datetime, timedelta, timezone

import autotrader_mtf_entry_shadow_v2 as mtf


def _obs(
    stamp: str,
    *,
    timeframe: int,
    macd: float,
    signal: float,
    close: float = 100.0,
) -> mtf.MtfObservationV2:
    bar_time = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return mtf.MtfObservationV2(
        bar_time=bar_time,
        closed_at=bar_time + timedelta(minutes=timeframe),
        timeframe_minutes=timeframe,
        close=close,
        macd=macd,
        signal=signal,
    )


def test_closed_5m_bars_exclude_forming_bucket() -> None:
    points = [
        (f"2026-09-01T04:{minute:02d}:00Z", 100.0 + minute)
        for minute in range(7)
    ]

    bars = mtf.closed_bars_v2(points, market="US Tech 100", timeframe_minutes=5)

    assert len(bars) == 1
    assert bars[0].bar_time.startswith("2026-09-01T04:00:00")
    assert bars[0].close == 104.0


def test_30m_context_allows_recovery_before_full_cross() -> None:
    previous = _obs(
        "2026-09-01T02:00:00Z",
        timeframe=30,
        macd=-8.0,
        signal=-3.0,
    )
    recovering = _obs(
        "2026-09-01T02:30:00Z",
        timeframe=30,
        macd=-5.0,
        signal=-2.0,
    )
    bullish = _obs(
        "2026-09-01T03:00:00Z",
        timeframe=30,
        macd=1.0,
        signal=0.0,
    )
    worsening = _obs(
        "2026-09-01T03:30:00Z",
        timeframe=30,
        macd=-9.0,
        signal=-3.0,
    )

    assert recovering.spread < 0
    assert mtf.regime_context_30m_v2(previous, recovering) == mtf.CONTEXT_RECOVERING
    assert mtf.regime_context_30m_v2(recovering, bullish) == mtf.CONTEXT_BULLISH
    assert mtf.regime_context_30m_v2(previous, worsening) == mtf.CONTEXT_BEARISH


def test_5m_cross_up_can_enter_before_10m_and_30m_crosses() -> None:
    previous = _obs(
        "2026-09-01T04:00:00Z",
        timeframe=5,
        macd=-2.0,
        signal=-1.0,
    )
    current = _obs(
        "2026-09-01T04:05:00Z",
        timeframe=5,
        macd=0.5,
        signal=0.0,
        close=29410.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_FLAT,
        timeframe_minutes=5,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_RECOVERING,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_ENTRY_5M
    assert decision.action == mtf.ACTION_WOULD_BUY
    assert decision.desired_state == mtf.STATE_PROVISIONAL_LONG


def test_5m_entry_is_blocked_while_30m_bearish_momentum_worsens() -> None:
    previous = _obs(
        "2026-09-01T04:00:00Z",
        timeframe=5,
        macd=-2.0,
        signal=-1.0,
    )
    current = _obs(
        "2026-09-01T04:05:00Z",
        timeframe=5,
        macd=0.5,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_FLAT,
        timeframe_minutes=5,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_BEARISH,
    )

    assert decision is None


def test_failed_5m_entry_exits_small_and_rearms() -> None:
    previous = _obs(
        "2026-09-01T04:10:00Z",
        timeframe=5,
        macd=1.0,
        signal=0.0,
    )
    current = _obs(
        "2026-09-01T04:15:00Z",
        timeframe=5,
        macd=-0.5,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_PROVISIONAL_LONG,
        timeframe_minutes=5,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_RECOVERING,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_REJECT_5M
    assert decision.action == mtf.ACTION_WOULD_EXIT_REARM
    assert decision.desired_state == mtf.STATE_FLAT


def test_10m_bullish_close_validates_provisional_entry() -> None:
    previous = _obs(
        "2026-09-01T04:00:00Z",
        timeframe=10,
        macd=-0.5,
        signal=0.0,
    )
    current = _obs(
        "2026-09-01T04:10:00Z",
        timeframe=10,
        macd=0.4,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_PROVISIONAL_LONG,
        timeframe_minutes=10,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_RECOVERING,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_CONFIRM_10M
    assert decision.desired_state == mtf.STATE_VALIDATED_10M


def test_10m_cross_down_rejects_before_30m_confirmation() -> None:
    previous = _obs(
        "2026-09-01T04:10:00Z",
        timeframe=10,
        macd=0.8,
        signal=0.0,
    )
    current = _obs(
        "2026-09-01T04:20:00Z",
        timeframe=10,
        macd=-0.2,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_VALIDATED_10M,
        timeframe_minutes=10,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_RECOVERING,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_REJECT_10M
    assert decision.action == mtf.ACTION_WOULD_EXIT_REARM
    assert decision.desired_state == mtf.STATE_FLAT


def test_30m_cross_up_is_confirmation_not_entry() -> None:
    previous = _obs(
        "2026-09-01T03:00:00Z",
        timeframe=30,
        macd=-1.0,
        signal=0.0,
    )
    current = _obs(
        "2026-09-01T03:30:00Z",
        timeframe=30,
        macd=0.2,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_VALIDATED_10M,
        timeframe_minutes=30,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_BULLISH,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_CONFIRM_30M
    assert decision.action == mtf.ACTION_CONFIRMATION
    assert decision.desired_state == mtf.STATE_CONFIRMED_30M


def test_30m_cross_down_ends_confirmed_long_regime() -> None:
    previous = _obs(
        "2026-09-01T05:00:00Z",
        timeframe=30,
        macd=0.8,
        signal=0.0,
    )
    current = _obs(
        "2026-09-01T05:30:00Z",
        timeframe=30,
        macd=-0.3,
        signal=0.0,
    )

    decision = mtf.decision_for_observation_v2(
        state=mtf.STATE_CONFIRMED_30M,
        timeframe_minutes=30,
        previous=previous,
        current=current,
        context_30m=mtf.CONTEXT_BEARISH,
    )

    assert decision is not None
    assert decision.event_type == mtf.EVENT_EXIT_30M
    assert decision.action == mtf.ACTION_WOULD_EXIT
    assert decision.desired_state == mtf.STATE_FLAT


def test_mtf_shadow_has_no_execution_authority() -> None:
    source = open("autotrader_mtf_entry_shadow_v2.py", encoding="utf-8").read()
    assert "trade/v2/orders" not in source
    assert "place_order(" not in source
    assert "execute_confirmed_manual_order" not in source
    assert "autotrader_live_open" not in source
    assert mtf.ACTION_WOULD_BUY == "WOULD_BUY"
