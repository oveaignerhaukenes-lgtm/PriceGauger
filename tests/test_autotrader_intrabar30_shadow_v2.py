from __future__ import annotations

from datetime import datetime, timedelta, timezone

import autotrader_intrabar30_shadow_v2 as intrabar
from autotrader_strategy_catalog_v2 import (
    AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2,
    AUTOTRADER_STRATEGIES_V2,
    INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2,
)


def _flat_history_then_move() -> tuple[tuple[str, float], ...]:
    """40 completed 30m buckets at 100, then a forming bucket moves to 110."""
    start = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
    points: list[tuple[str, float]] = []
    for index in range(40):
        # One final 1m close per historical bucket is enough for the close-only MACD path.
        stamp = start + timedelta(minutes=index * 30 + 29)
        points.append((stamp.isoformat(), 100.0))
    forming = start + timedelta(minutes=40 * 30)
    points.append((forming.isoformat(), 100.0))
    points.append(((forming + timedelta(minutes=1)).isoformat(), 110.0))
    return tuple(points)


def test_intrabar_clock_can_cross_before_30m_bar_close():
    samples = intrabar.intrabar_macd_samples_v2(
        _flat_history_then_move(),
        market="US Tech 100 NAS · Saxo 4912",
    )

    assert len(samples) >= 2
    previous, current = samples[-2], samples[-1]
    assert previous.bucket_start == current.bucket_start
    assert previous.minute_offset == 1
    assert current.minute_offset == 2
    assert previous.spread == 0.0
    assert current.spread > 0.0
    assert intrabar._cross_spread_v2(previous.spread, current.spread) == intrabar.SIGNAL_UP
    assert current.minute_offset < 30


def test_cross_event_records_exact_minute_inside_30m_bucket():
    state = intrabar.Intrabar30ShadowStateV2(
        market_id=1,
        market_name="US Tech 100 NAS · Saxo 4912",
        state=intrabar.STATE_FLAT,
        last_sample_at=datetime(2026, 9, 1, 7, 4, tzinfo=timezone.utc),
        last_spread=-0.25,
    )
    sample = intrabar.IntrabarMacdSampleV2(
        action_at=datetime(2026, 9, 1, 7, 5, tzinfo=timezone.utc),
        bucket_start=datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc),
        minute_offset=5,
        price=29443.4,
        macd=2.0,
        signal=1.8,
    )

    event = intrabar._event_for_cross_v2(
        state=state,
        sample=sample,
        previous_spread=-0.25,
        signal=intrabar.SIGNAL_UP,
    )

    assert event is not None
    assert event.action == intrabar.ACTION_WOULD_BUY
    assert event.desired_state == intrabar.STATE_LONG
    assert event.minute_offset == 5
    assert event.bucket_start == datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc)


def test_intrabar_cross_can_uncross_and_exit_in_same_30m_bucket():
    long_state = intrabar.Intrabar30ShadowStateV2(
        market_id=1,
        market_name="US Tech 100",
        state=intrabar.STATE_LONG,
        last_spread=0.1,
    )
    sample = intrabar.IntrabarMacdSampleV2(
        action_at=datetime(2026, 9, 1, 7, 12, tzinfo=timezone.utc),
        bucket_start=datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc),
        minute_offset=12,
        price=29420.0,
        macd=-1.0,
        signal=-0.8,
    )
    crossing = intrabar._cross_spread_v2(0.1, sample.spread)
    assert crossing == intrabar.SIGNAL_DOWN
    event = intrabar._event_for_cross_v2(
        state=long_state,
        sample=sample,
        previous_spread=0.1,
        signal=crossing,
    )
    assert event is not None
    assert event.action == intrabar.ACTION_WOULD_EXIT
    assert event.desired_state == intrabar.STATE_FLAT


def test_intrabar_template_is_experimental_not_live_capable():
    live_keys = {item.key for item in AUTOTRADER_STRATEGIES_V2}
    assert INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2 not in live_keys
    assert AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2.live_ready is False
    assert AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2.shadow_running is False


def test_intrabar_shadow_has_no_execution_authority():
    source = open("autotrader_intrabar30_shadow_v2.py", encoding="utf-8").read()
    forbidden = (
        "trade/v2/orders",
        "place_order(",
        "autotrader_live_open",
        "autotrader_live_close",
        "execute_confirmed_manual_order",
    )
    for token in forbidden:
        assert token not in source
    assert intrabar.SOURCE_KIND == "CANONICAL_1M_CLOSE"
