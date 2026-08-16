from __future__ import annotations

import inspect

import context_runtime_v2
from context_runtime_v2 import apply_context_freshness_v2, publish_context_snapshot_v2
from context_snapshot_store_v2 import ContextSnapshotStoreV2
from context_snapshot_v2 import (
    FRESH,
    STALE,
    UNKNOWN,
    SCOPE_GLOBAL,
    ContextEvidenceRefV2,
    ContextTargetStateV2,
    build_context_snapshot_v2,
)


def _snapshot():
    evidence = ContextEvidenceRefV2(
        evidence_id="telegram:channel:1",
        source_kind="TELEGRAM",
        source_scope=SCOPE_GLOBAL,
        source_id="channel",
        observed_at="2026-08-17T00:00:00Z",
        published_at="2026-08-16T23:59:00Z",
    )
    return build_context_snapshot_v2(
        as_of="2026-08-17T00:00:00Z",
        engine_version="test",
        scope_key="global",
        freshness_status=UNKNOWN,
        evidence=(evidence,),
        targets=(
            ContextTargetStateV2(
                target_key="Gold",
                directional_bias=0.2,
                confidence=0.6,
                novelty=0.4,
                event_risk=0.3,
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
        coverage_start="2026-08-16T23:00:00Z",
        coverage_end="2026-08-17T00:00:00Z",
    )


def test_freshness_uses_coverage_end_and_explicit_threshold():
    snapshot = _snapshot()

    fresh = apply_context_freshness_v2(
        snapshot,
        evaluated_at="2026-08-17T00:04:59Z",
        max_age_seconds=300,
    )
    stale = apply_context_freshness_v2(
        snapshot,
        evaluated_at="2026-08-17T00:05:01Z",
        max_age_seconds=300,
    )

    assert fresh.freshness_status == FRESH
    assert stale.freshness_status == STALE
    assert fresh.state_fingerprint != stale.state_fingerprint


def test_publish_rejects_repeated_poll_but_persists_freshness_transition(tmp_path):
    store = ContextSnapshotStoreV2(tmp_path / "context.db")
    snapshot = _snapshot()

    first, first_saved = publish_context_snapshot_v2(
        snapshot,
        store=store,
        evaluated_at="2026-08-17T00:04:00Z",
    )
    repeated, repeated_saved = publish_context_snapshot_v2(
        snapshot,
        store=store,
        evaluated_at="2026-08-17T00:04:30Z",
    )
    stale, stale_saved = publish_context_snapshot_v2(
        snapshot,
        store=store,
        evaluated_at="2026-08-17T00:06:00Z",
    )

    assert first.freshness_status == FRESH
    assert repeated.freshness_status == FRESH
    assert stale.freshness_status == STALE
    assert first_saved is True
    assert repeated_saved is False
    assert stale_saved is True


def test_runtime_has_no_semantic_generation_technical_composer_or_execution_authority():
    source = inspect.getsource(context_runtime_v2)
    forbidden = (
        "state_runtime_pipeline",
        "technical_core",
        "context_adapter_v2",
        "openai",
        "place_order",
        "AutoTrader",
        "Holistic",
    )
    for token in forbidden:
        assert token not in source
