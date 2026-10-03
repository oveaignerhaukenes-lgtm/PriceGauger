from dataclasses import fields

from skilled_money_snapshot_v1 import SkilledMoneySnapshotV1


def test_snapshot_contract_stores_analysis_not_raw_feed() -> None:
    names = {field.name for field in fields(SkilledMoneySnapshotV1)}
    assert {"technical_regime", "world_regime", "actor_state", "revisions"} <= names
    assert "raw_ticks" not in names
    assert "order_book_feed" not in names
