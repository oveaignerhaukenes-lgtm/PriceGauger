import pandas as pd

from signal_aggregator import EventSignal, aggregate_event_signals


def _signal(
    event_id: str,
    direction: str,
    expected: float | None,
    weight: float,
    contribution: float,
    grade: str = "MEDIUM",
) -> EventSignal:
    return EventSignal(
        event_id=event_id,
        title=event_id,
        published_at="2026-07-20T12:00:00+00:00",
        event_type="attack",
        target="shipping",
        direction=direction,
        confidence_pct=75.0,
        expected_move_pct=expected,
        evidence_grade=grade,
        analogue_sample=8,
        effective_analogue_sample=5.0,
        source_quality=0.9,
        severity=0.8,
        age_hours=1.0,
        freshness_weight=0.9,
        signal_weight=weight,
        contribution=contribution,
    )


def test_aggregate_requires_more_than_one_usable_event() -> None:
    result = aggregate_event_signals(
        asset="Brent",
        signals=[_signal("one", "LONG", 0.4, 0.8, 0.64)],
        window_hours=24,
    )

    assert result.evidence_grade == "INSUFFICIENT"
    assert result.direction == "NEUTRAL"


def test_aggregate_combines_individual_signals_after_scoring() -> None:
    signals = [
        _signal("attack-a", "LONG", 0.50, 1.0, 1.0),
        _signal("attack-b", "LONG", 0.30, 0.8, 0.48),
        _signal("diplomacy", "SHORT", -0.20, 0.25, -0.10),
    ]

    result = aggregate_event_signals(
        asset="Brent",
        signals=signals,
        window_hours=12,
        now=pd.Timestamp("2026-07-20T13:00:00Z"),
    )

    assert result.direction == "LONG"
    assert result.events_used == 3
    assert result.long_events == 2
    assert result.short_events == 1
    assert result.net_score > 0.12
    assert result.expected_move_pct is not None
    assert result.expected_move_pct > 0


def test_insufficient_and_neutral_events_do_not_drive_direction() -> None:
    signals = [
        _signal("good-long", "LONG", 0.4, 0.8, 0.64),
        _signal("good-short", "SHORT", -0.2, 0.7, -0.28),
        _signal("bad", "SHORT", -2.0, 10.0, -10.0, grade="INSUFFICIENT"),
        _signal("neutral", "NEUTRAL", 0.0, 10.0, 0.0),
    ]

    result = aggregate_event_signals(
        asset="Gold",
        signals=signals,
        now=pd.Timestamp("2026-07-20T13:00:00Z"),
    )

    assert result.events_used == 2
    assert result.neutral_events == 2
    assert result.net_score > 0
