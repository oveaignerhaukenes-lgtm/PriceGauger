from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from context_snapshot_store_v2 import ContextSnapshotStoreV2


_DIRECTIONAL_DEADBAND = 0.05
_MIN_DIRECTION_CONFIDENCE = 0.20


@dataclass(frozen=True, slots=True)
class ContextOverviewTargetV2:
    target_key: str
    directional_bias: float
    confidence: float
    novelty: float
    event_risk: float
    summary: str

    @property
    def direction_label(self) -> str:
        bias = float(self.directional_bias)
        confidence = float(self.confidence)
        if abs(bias) <= _DIRECTIONAL_DEADBAND:
            return "NEUTRAL"
        if confidence < _MIN_DIRECTION_CONFIDENCE:
            return "UNCERTAIN"
        return "BULLISH" if bias > 0 else "BEARISH"


@dataclass(frozen=True, slots=True)
class ContextOverviewEvidenceV2:
    evidence_id: str
    source_kind: str
    source_scope: str
    source_id: str
    observed_at: str
    published_at: str
    user_scope_id: str
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextOverviewV2:
    snapshot_id: str
    as_of: str
    freshness_status: str
    engine_version: str
    regime_label: str
    summary: str
    coverage_start: str
    coverage_end: str
    targets: tuple[ContextOverviewTargetV2, ...]
    evidence: tuple[ContextOverviewEvidenceV2, ...]


def load_context_overview_v2(
    db_path: str | Path = "pricegauger.db",
    *,
    scope_key: str = "global",
) -> ContextOverviewV2 | None:
    """Project the canonical ContextSnapshotV2 into an Overview-safe read model."""
    snapshot = ContextSnapshotStoreV2(db_path).load_latest(scope_key=scope_key)
    if snapshot is None:
        return None

    targets = tuple(
        ContextOverviewTargetV2(
            target_key=item.target_key,
            directional_bias=float(item.directional_bias),
            confidence=float(item.confidence),
            novelty=float(item.novelty),
            event_risk=float(item.event_risk),
            summary=item.summary,
        )
        for item in sorted(snapshot.targets, key=lambda item: item.target_key.casefold())
    )
    evidence = tuple(
        ContextOverviewEvidenceV2(
            evidence_id=item.evidence_id,
            source_kind=item.source_kind,
            source_scope=item.source_scope,
            source_id=item.source_id,
            observed_at=item.observed_at,
            published_at=item.published_at,
            user_scope_id=item.user_scope_id,
            tags=item.tags,
        )
        for item in reversed(snapshot.evidence)
    )
    return ContextOverviewV2(
        snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        freshness_status=snapshot.freshness_status,
        engine_version=snapshot.engine_version,
        regime_label=snapshot.regime_label,
        summary=snapshot.summary,
        coverage_start=snapshot.coverage_start,
        coverage_end=snapshot.coverage_end,
        targets=targets,
        evidence=evidence,
    )
