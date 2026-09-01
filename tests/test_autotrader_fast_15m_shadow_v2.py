from datetime import datetime, timezone

import autotrader_fast_15m_shadow_v2 as fast
from autotrader_mtf_entry_shadow_v2 import MtfObservationV2


def _obs(stamp: str, macd: float, signal: float, close: float = 100.0) -> MtfObservationV2:
    at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return MtfObservationV2(
        bar_time=at,
        closed_at=at,
        timeframe_minutes=15,
        close=close,
        macd=macd,
        signal=signal,
    )


def test_fast15_cross_is_directional():
    equal = _obs("2026-09-01T04:00:00Z", 1.0, 1.0)
    above = _obs("2026-09-01T04:15:00Z", 1.2, 1.0)
    below = _obs("2026-09-01T04:30:00Z", 0.8, 1.0)

    assert fast._cross(equal, above) == fast.SIGNAL_UP
    assert fast._cross(above, below) == fast.SIGNAL_DOWN
    assert fast._cross(below, below) is None


def test_fast15_long_flat_policy_only_changes_on_relevant_crosses():
    state = fast.Fast15ShadowStateV2(market_id=7, market_name="US Tech")
    down = _obs("2026-09-01T04:00:00Z", 0.8, 1.0)
    up = _obs("2026-09-01T04:15:00Z", 1.2, 1.0, close=101.0)

    entry = fast._event_for_cross_v2(
        state=state,
        previous=down,
        current=up,
        signal=fast.SIGNAL_UP,
    )
    assert entry is not None
    assert entry.action == fast.ACTION_WOULD_BUY
    assert entry.desired_state == fast.STATE_LONG

    long_state = fast.Fast15ShadowStateV2(
        market_id=7,
        market_name="US Tech",
        state=fast.STATE_LONG,
    )
    exit_event = fast._event_for_cross_v2(
        state=long_state,
        previous=up,
        current=down,
        signal=fast.SIGNAL_DOWN,
    )
    assert exit_event is not None
    assert exit_event.action == fast.ACTION_WOULD_EXIT
    assert exit_event.desired_state == fast.STATE_FLAT

    assert fast._event_for_cross_v2(
        state=long_state,
        previous=down,
        current=up,
        signal=fast.SIGNAL_UP,
    ) is None


def test_fast15_event_identity_is_restart_stable():
    state = fast.Fast15ShadowStateV2(market_id=7, market_name="US Tech")
    previous = _obs("2026-09-01T04:00:00Z", 0.8, 1.0)
    current = _obs("2026-09-01T04:15:00Z", 1.2, 1.0)

    first = fast._event_for_cross_v2(
        state=state,
        previous=previous,
        current=current,
        signal=fast.SIGNAL_UP,
    )
    second = fast._event_for_cross_v2(
        state=state,
        previous=previous,
        current=current,
        signal=fast.SIGNAL_UP,
    )
    assert first is not None and second is not None
    assert first.event_id == second.event_id


def test_fast15_module_has_no_execution_authority():
    source = open("autotrader_fast_15m_shadow_v2.py", encoding="utf-8").read()
    assert "place_order(" not in source
    assert ".precheck(" not in source
    assert "execute_confirmed_manual_order" not in source
    assert "autotrader_live_open" not in source
    assert "autotrader_live_close" not in source
