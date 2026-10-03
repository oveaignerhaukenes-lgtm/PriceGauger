from skilled_money_snapshot_v1 import SkilledMoneyEvidenceV1


def test_evidence_kind_accepts_retrospective_states() -> None:
    states = ("OBSERVED", "INFERRED", "CONFIRMED", "WEAKENED", "REFUTED")
    for state in states:
        item = SkilledMoneyEvidenceV1("x", "x", state)  # type: ignore[arg-type]
        assert item.kind == state
