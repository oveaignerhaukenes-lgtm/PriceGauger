from datetime import datetime, timedelta, timezone

import autotrader_mtf_live_runtime_v2 as live
from autotrader_mtf_entry_shadow_v2 import (
    ACTION_CONFIRMATION,
    ACTION_WOULD_BUY,
    ACTION_WOULD_EXIT_REARM,
    MtfDecisionV2,
    MtfObservationV2,
    STATE_FLAT,
    STATE_PROVISIONAL_LONG,
)


NOW = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)


def obs(*, closed_at: datetime, timeframe: int, spread: float, close: float = 100.0):
    return MtfObservationV2(
        bar_time=closed_at - timedelta(minutes=timeframe),
        closed_at=closed_at,
        timeframe_minutes=timeframe,
        close=close,
        macd=spread,
        signal=0.0,
    )


def test_live_target_mapping_preserves_long_flat_only():
    entry = MtfDecisionV2(
        event_type="ENTRY_5M",
        action=ACTION_WOULD_BUY,
        desired_state=STATE_PROVISIONAL_LONG,
        reason="entry",
    )
    reject = MtfDecisionV2(
        event_type="REJECT_5M",
        action=ACTION_WOULD_EXIT_REARM,
        desired_state=STATE_FLAT,
        reason="reject",
    )
    confirm = MtfDecisionV2(
        event_type="CONFIRM_10M",
        action=ACTION_CONFIRMATION,
        desired_state="VALIDATED_10M",
        reason="confirm",
    )

    assert live._target_direction(entry) == "LONG"
    assert live._target_direction(reject) == "FLAT"
    assert live._target_direction(confirm) is None
    assert live._request_action("FLAT", "LONG") == "OPEN"
    assert live._request_action("LONG", "LONG") is None  # never pyramid
    assert live._request_action("LONG", "FLAT") == "CLOSE"
    assert live._request_action("FLAT", "FLAT") is None


def test_latest_work_never_replays_intermediate_outage_bars():
    state = live.MtfLiveStateV2(
        pilot_key="pilot",
        state=STATE_FLAT,
        last_5m_closed_at=NOW - timedelta(minutes=25),
        last_10m_closed_at=NOW - timedelta(minutes=30),
        last_30m_closed_at=NOW - timedelta(minutes=60),
    )
    by_tf = {
        5: tuple(obs(closed_at=NOW - timedelta(minutes=m), timeframe=5, spread=float(m)) for m in (20, 15, 10, 5, 0)),
        10: tuple(obs(closed_at=NOW - timedelta(minutes=m), timeframe=10, spread=float(m)) for m in (20, 10, 0)),
        30: tuple(obs(closed_at=NOW - timedelta(minutes=m), timeframe=30, spread=float(m)) for m in (30, 0)),
    }

    work = live._latest_work(state, by_tf, now=NOW)

    assert len(work) == 3
    assert {item[0] for item in work} == {5, 10, 30}
    assert all(current.closed_at == NOW for _, _, current, _ in work)
    assert all(fresh is True for _, _, _, fresh in work)


def test_market_closed_stale_sample_advances_cursor_but_is_not_actionable():
    state = live.MtfLiveStateV2(pilot_key="pilot", state=STATE_FLAT)
    old = NOW - timedelta(hours=4)
    by_tf = {
        5: (obs(closed_at=old - timedelta(minutes=5), timeframe=5, spread=-1), obs(closed_at=old, timeframe=5, spread=1)),
        10: (obs(closed_at=old - timedelta(minutes=10), timeframe=10, spread=-1), obs(closed_at=old, timeframe=10, spread=1)),
        30: (obs(closed_at=old - timedelta(minutes=30), timeframe=30, spread=-1), obs(closed_at=old, timeframe=30, spread=1)),
    }
    work = live._latest_work(state, by_tf, now=NOW)
    assert len(work) == 3
    assert all(fresh is False for _, _, _, fresh in work)


def test_mtf_live_has_no_direct_order_post_path():
    source = open("autotrader_mtf_live_runtime_v2.py", encoding="utf-8").read()
    forbidden = (
        "trade/v2/orders",
        "_post_once(",
        "session.post(",
        "place_order(",
        "live_open_order_payload_v2",
    )
    for token in forbidden:
        assert token not in source
    assert "pg_v2_autotrader_execution_requests" in source
    assert "ON CONFLICT (request_id) DO NOTHING" in source


def test_base_runtime_dispatches_mtf_instead_of_closed_30m_adapter():
    source = open("autotrader_automanage_runtime_v2.py", encoding="utf-8").read()
    assert "enrollment.strategy_key == MTF_LONG_FLAT_STRATEGY_V2" in source
    assert "run_mtf_live_strategy_once_v2" in source
