from datetime import datetime, timezone

from skilled_money_snapshot_v1 import (
    SkilledMoneyEvidenceV1,
    SkilledMoneyRevisionV1,
    SkilledMoneySnapshotV1,
)


def test_snapshot_keeps_original_and_later_revision() -> None:
    t0 = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    observed = SkilledMoneyEvidenceV1(
        label="rates",
        statement="Rates rose during the move",
        kind="OBSERVED",
        confidence=1.0,
        available_at=t0,
    )
    initial = SkilledMoneyRevisionV1(1, t0, "Rates repricing observed", (observed,))
    later = SkilledMoneyRevisionV1(2, t0, "Later positioning weakens CTA hypothesis", ())
    snapshot = SkilledMoneySnapshotV1(
        event_id="demo",
        instrument="US Tech 100",
        event_started_at=t0,
        event_ended_at=None,
        move_summary="sharp decline",
        revisions=(initial, later),
    )

    assert snapshot.revisions[0] is initial
    assert snapshot.latest_revision is later
    assert snapshot.revisions[0].evidence[0].kind == "OBSERVED"
