from __future__ import annotations

from context_snapshot_v2 import (
    FRESH,
    SCOPE_GLOBAL,
    SCOPE_USER,
    ContextDimensionV2,
    ContextEvidenceRefV2,
    ContextTargetStateV2,
    build_context_snapshot_v2,
    materially_changed_v2,
)


def _evidence(*, evidence_id: str = "telegram:1", scope: str = SCOPE_GLOBAL, user_scope_id: str = ""):
    return ContextEvidenceRefV2(
        evidence_id=evidence_id,
        source_kind="TELEGRAM",
        source_scope=scope,
        source_id="Middle_East_Spectator",
        observed_at="2026-08-16T20:00:00Z",
        published_at="2026-08-16T19:59:00Z",
        user_scope_id=user_scope_id,
    )


def _target(*, summary: str = "Escalation pressure"):
    return ContextTargetStateV2(
        target_key="GOLD",
        directional_bias=0.4,
        confidence=0.7,
        novelty=0.8,
        event_risk=0.6,
        evidence_ids=("telegram:1",),
        dimensions=(
            ContextDimensionV2(
                name="physical_supply_risk",
                value=0.3,
                confidence=0.6,
                evidence_ids=("telegram:1",),
                horizon_hours=4,
            ),
        ),
        summary=summary,
    )


def _snapshot(*, as_of: str = "2026-08-16T20:01:00Z", summary: str = "Escalation pressure"):
    return build_context_snapshot_v2(
        as_of=as_of,
        engine_version="context-engine-v2-test",
        scope_key="global",
        freshness_status=FRESH,
        coverage_start="2026-08-16T19:00:00Z",
        coverage_end="2026-08-16T19:59:00Z",
        evidence=(_evidence(),),
        targets=(_target(summary=summary),),
        regime_label="elevated geopolitical risk",
        summary=summary,
    )


def test_polling_time_does_not_change_semantic_fingerprint():
    first = _snapshot(as_of="2026-08-16T20:01:00Z")
    later = _snapshot(as_of="2026-08-16T20:02:00Z")

    assert first.snapshot_id != later.snapshot_id
    assert first.state_fingerprint == later.state_fingerprint
    assert not materially_changed_v2(first, later)


def test_semantic_change_changes_fingerprint():
    first = _snapshot(summary="Escalation pressure")
    changed = _snapshot(summary="De-escalation pressure")

    assert first.state_fingerprint != changed.state_fingerprint
    assert materially_changed_v2(first, changed)


def test_user_scoped_evidence_requires_user_identity():
    try:
        _evidence(scope=SCOPE_USER)
    except ValueError as exc:
        assert "user_scope_id" in str(exc)
    else:
        raise AssertionError("USER_SCOPED evidence must require user_scope_id")


def test_user_and_global_provenance_are_explicit():
    global_ref = _evidence()
    user_ref = _evidence(
        evidence_id="telegram:user:42",
        scope=SCOPE_USER,
        user_scope_id="user-42",
    )

    assert global_ref.source_scope == SCOPE_GLOBAL
    assert global_ref.user_scope_id == ""
    assert user_ref.source_scope == SCOPE_USER
    assert user_ref.user_scope_id == "user-42"


def test_extensible_dimension_names_do_not_require_contract_change():
    dimension = ContextDimensionV2(
        name="future_custom_worldview_dimension",
        value=-0.2,
        confidence=0.55,
        evidence_ids=("e1",),
    )

    assert dimension.name == "future_custom_worldview_dimension"
