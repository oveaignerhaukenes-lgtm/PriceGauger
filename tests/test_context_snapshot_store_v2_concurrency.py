from __future__ import annotations

from context_snapshot_store_v2 import ContextSnapshotStoreV2
from context_snapshot_v2 import FRESH, build_context_snapshot_v2


def test_duplicate_empty_state_is_idempotent(tmp_path):
    store = ContextSnapshotStoreV2(tmp_path / "context.db")
    snapshot = build_context_snapshot_v2(
        as_of="2026-08-17T00:00:00Z",
        engine_version="test",
        scope_key="global",
        freshness_status=FRESH,
        evidence=(),
        targets=(),
    )

    assert store.save_if_material_change(snapshot) is True
    assert store.save_if_material_change(snapshot) is False
