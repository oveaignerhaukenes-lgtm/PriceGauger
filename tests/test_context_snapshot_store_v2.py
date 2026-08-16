from __future__ import annotations

import inspect

import context_snapshot_store_v2
from context_snapshot_store_v2 import ContextSnapshotStoreV2
from context_snapshot_v2 import (
    FRESH,
    STALE,
    SCOPE_GLOBAL,
    ContextEvidenceRefV2,
    ContextTargetStateV2,
    build_context_snapshot_v2,
)


def _snapshot(*, as_of: str, bias: float = 0.4, freshness: str = FRESH, summary: str = "first"):
    evidence = ContextEvidenceRefV2(
        evidence_id="telegram:channel:42",
        source_kind="TELEGRAM",
        source_scope=SCOPE_GLOBAL,
        source_id="channel",
        observed_at="2026-08-17T00:00:00Z",
        published_at="2026-08-16T23:59:00Z",
    )
    target = ContextTargetStateV2(
        target_key="Gold",
        directional_bias=bias,
        confidence=0.7,
        novelty=0.8,
        event_risk=0.5,
        evidence_ids=(evidence.evidence_id,),
    )
    return build_context_snapshot_v2(
        as_of=as_of,
        engine_version="test-context-v2",
        scope_key="global",
        freshness_status=freshness,
        evidence=(evidence,),
        targets=(target,),
        coverage_start="2026-08-16T23:00:00Z",
        coverage_end="2026-08-17T00:00:00Z",
        regime_label="test-regime",
        summary=summary,
    )


def test_store_persists_first_snapshot_and_round_trips(tmp_path):
    store = ContextSnapshotStoreV2(tmp_path / "context.db")
    snapshot = _snapshot(as_of="2026-08-17T00:01:00Z")

    assert store.save_if_material_change(snapshot) is True
    loaded = store.load_latest()

    assert loaded == snapshot
    assert loaded.state_fingerprint == snapshot.state_fingerprint


def test_poll_time_and_summary_churn_do_not_create_new_semantic_state(tmp_path):
    store = ContextSnapshotStoreV2(tmp_path / "context.db")
    first = _snapshot(as_of="2026-08-17T00:01:00Z", summary="wording A")
    repoll = _snapshot(as_of="2026-08-17T00:02:00Z", summary="wording B")

    assert first.state_fingerprint == repoll.state_fingerprint
    assert store.save_if_material_change(first) is True
    assert store.save_if_material_change(repoll) is False

    with store._connect() as db:
        count = db.execute("SELECT COUNT(*) AS n FROM context_v2_snapshots").fetchone()["n"]
    assert count == 1


def test_semantic_and_freshness_changes_append_new_state(tmp_path):
    store = ContextSnapshotStoreV2(tmp_path / "context.db")
    first = _snapshot(as_of="2026-08-17T00:01:00Z")
    changed = _snapshot(as_of="2026-08-17T00:02:00Z", bias=-0.2)
    stale = _snapshot(as_of="2026-08-17T00:03:00Z", bias=-0.2, freshness=STALE)

    assert store.save_if_material_change(first) is True
    assert store.save_if_material_change(changed) is True
    assert store.save_if_material_change(stale) is True
    assert store.load_latest() == stale


def test_store_has_no_legacy_runtime_composer_llm_or_execution_authority():
    source = inspect.getsource(context_snapshot_store_v2)
    forbidden = (
        "state_runtime_pipeline",
        "process_flow_snapshot",
        "technical_core",
        "context_adapter_v2",
        "openai",
        "place_order",
        "AutoTrader",
    )
    for token in forbidden:
        assert token not in source
