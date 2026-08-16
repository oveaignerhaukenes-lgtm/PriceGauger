from __future__ import annotations

from datetime import datetime, timezone

from context_snapshot_store_v2 import ContextSnapshotStoreV2
from context_snapshot_v2 import (
    FRESH,
    STALE,
    ContextSnapshotV2,
    build_context_snapshot_v2,
)


DEFAULT_CONTEXT_FRESHNESS_SECONDS = 300


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def apply_context_freshness_v2(
    snapshot: ContextSnapshotV2,
    *,
    evaluated_at: str | None = None,
    max_age_seconds: int = DEFAULT_CONTEXT_FRESHNESS_SECONDS,
) -> ContextSnapshotV2:
    """Return a snapshot with explicit runtime freshness state.

    Freshness is based on coverage_end when present, otherwise snapshot as_of. The
    policy is intentionally outside the semantic adapter so polling and translation
    remain independent from runtime policy.

    A freshness transition is a material semantic-state transition. Rebuild through
    the canonical constructor so the new fingerprint and immutable snapshot identity
    remain consistent instead of mutating the prior identity in place.
    """
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    now = _utc(evaluated_at) if evaluated_at else datetime.now(timezone.utc)
    reference = _utc(snapshot.coverage_end or snapshot.as_of)
    age_seconds = max(0.0, (now - reference).total_seconds())
    status = FRESH if age_seconds <= max_age_seconds else STALE
    if snapshot.freshness_status == status:
        return snapshot
    return build_context_snapshot_v2(
        as_of=snapshot.as_of,
        engine_version=snapshot.engine_version,
        scope_key=snapshot.scope_key,
        freshness_status=status,
        coverage_start=snapshot.coverage_start,
        coverage_end=snapshot.coverage_end,
        evidence=snapshot.evidence,
        targets=snapshot.targets,
        regime_label=snapshot.regime_label,
        summary=snapshot.summary,
    )


def publish_context_snapshot_v2(
    snapshot: ContextSnapshotV2,
    *,
    store: ContextSnapshotStoreV2,
    evaluated_at: str | None = None,
    max_age_seconds: int = DEFAULT_CONTEXT_FRESHNESS_SECONDS,
) -> tuple[ContextSnapshotV2, bool]:
    """Apply freshness policy and persist only a material semantic-state transition."""
    evaluated = apply_context_freshness_v2(
        snapshot,
        evaluated_at=evaluated_at,
        max_age_seconds=max_age_seconds,
    )
    persisted = store.save_if_material_change(evaluated)
    return evaluated, persisted
