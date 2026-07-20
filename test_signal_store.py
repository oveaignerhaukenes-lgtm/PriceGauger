from pathlib import Path

import pandas as pd

from signal_aggregator import EventSignal, aggregate_event_signals
from signal_store import SignalStore


def _signal(event_id: str, asset: str, published_at: str, direction: str = "LONG") -> EventSignal:
    sign = 1.0 if direction == "LONG" else -1.0
    return EventSignal(
        event_id=event_id,
        title=event_id,
        published_at=published_at,
        event_type="attack",
        target="shipping",
        direction=direction,
        confidence_pct=75.0,
        expected_move_pct=0.5 * sign,
        evidence_grade="MEDIUM",
        analogue_sample=8,
        effective_analogue_sample=5.0,
        source_quality=0.9,
        severity=0.8,
        age_hours=0.0,
        freshness_weight=1.0,
        signal_weight=0.8,
        contribution=0.8 * sign,
        asset=asset,
        half_life_hours=6.0,
        max_age_hours=24.0,
    )


def test_store_upserts_and_filters_active_signals(tmp_path: Path) -> None:
    store = SignalStore(tmp_path / "signals.sqlite3")
    now = pd.Timestamp("2026-07-20T12:00:00Z")
    store.add(_signal("fresh", "Brent", "2026-07-20T10:00:00Z"))
    store.add(_signal("old", "Brent", "2026-07-18T10:00:00Z"))
    store.add(_signal("other", "Gold", "2026-07-20T11:00:00Z"))

    active = store.active("Brent", window_hours=24, now=now)

    assert [signal.event_id for signal in active] == ["fresh"]
    assert len(store.all("Gold")) == 1


def test_aggregator_can_run_only_from_stored_signals(tmp_path: Path) -> None:
    store = SignalStore(tmp_path / "signals.sqlite3")
    now = pd.Timestamp("2026-07-20T12:00:00Z")
    store.add(_signal("long-a", "Silver", "2026-07-20T11:00:00Z"))
    store.add(_signal("long-b", "Silver", "2026-07-20T10:00:00Z"))

    result = aggregate_event_signals(
        asset="Silver",
        signals=store.active("Silver", window_hours=24, now=now),
        window_hours=24,
        now=now,
    )

    assert result.events_used == 2
    assert result.direction == "LONG"
    assert result.net_score > 0


def test_purge_expired_removes_only_stale_rows(tmp_path: Path) -> None:
    store = SignalStore(tmp_path / "signals.sqlite3")
    now = pd.Timestamp("2026-07-20T12:00:00Z")
    store.add(_signal("fresh", "Brent", "2026-07-20T11:00:00Z"))
    store.add(_signal("old", "Brent", "2026-07-18T11:00:00Z"))

    removed = store.purge_expired(now=now)

    assert removed == 1
    assert [signal.event_id for signal in store.all("Brent")] == ["fresh"]
