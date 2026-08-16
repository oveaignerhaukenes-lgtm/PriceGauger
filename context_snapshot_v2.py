from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5


CONTEXT_CONTRACT_VERSION = "context-snapshot-v2"
SCOPE_GLOBAL = "GLOBAL_SHARED"
SCOPE_USER = "USER_SCOPED"
FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"


def _iso_utc(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _bounded(value: float, field: str, low: float = 0.0, high: float = 1.0) -> float:
    result = float(value)
    if not low <= result <= high:
        raise ValueError(f"{field} must be between {low} and {high}")
    return result


def _non_empty(value: str, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


@dataclass(frozen=True, slots=True)
class ContextEvidenceRefV2:
    """Stable provenance pointer owned by the Context bounded context.

    source_kind is intentionally open-ended so future sources do not require a
    contract rewrite. source_scope is restricted because global-vs-user ownership
    is an architectural boundary, not a presentation detail.
    """

    evidence_id: str
    source_kind: str
    source_scope: str
    source_id: str
    observed_at: str
    published_at: str = ""
    user_scope_id: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _non_empty(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "source_kind", _non_empty(self.source_kind, "source_kind"))
        object.__setattr__(self, "source_id", _non_empty(self.source_id, "source_id"))
        if self.source_scope not in {SCOPE_GLOBAL, SCOPE_USER}:
            raise ValueError("source_scope must be GLOBAL_SHARED or USER_SCOPED")
        if self.source_scope == SCOPE_USER and not str(self.user_scope_id or "").strip():
            raise ValueError("USER_SCOPED evidence requires user_scope_id")
        if self.source_scope == SCOPE_GLOBAL and str(self.user_scope_id or "").strip():
            raise ValueError("GLOBAL_SHARED evidence cannot carry user_scope_id")
        object.__setattr__(self, "observed_at", _iso_utc(self.observed_at))
        if self.published_at:
            object.__setattr__(self, "published_at", _iso_utc(self.published_at))
        object.__setattr__(self, "tags", tuple(sorted({str(item).strip() for item in self.tags if str(item).strip()})))


@dataclass(frozen=True, slots=True)
class ContextDimensionV2:
    """Extensible semantic state dimension.

    name is intentionally not an enum. New dimensions may be added later without
    changing the public contract shape.
    """

    name: str
    value: float
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    horizon_hours: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, "dimension.name"))
        object.__setattr__(self, "value", _bounded(self.value, "dimension.value", -1.0, 1.0))
        object.__setattr__(self, "confidence", _bounded(self.confidence, "dimension.confidence"))
        if self.horizon_hours is not None and float(self.horizon_hours) <= 0:
            raise ValueError("dimension.horizon_hours must be positive")
        object.__setattr__(self, "evidence_ids", tuple(sorted({str(item).strip() for item in self.evidence_ids if str(item).strip()})))


@dataclass(frozen=True, slots=True)
class ContextTargetStateV2:
    target_key: str
    directional_bias: float
    confidence: float
    novelty: float
    event_risk: float
    evidence_ids: tuple[str, ...] = ()
    dimensions: tuple[ContextDimensionV2, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_key", _non_empty(self.target_key, "target_key"))
        object.__setattr__(self, "directional_bias", _bounded(self.directional_bias, "directional_bias", -1.0, 1.0))
        object.__setattr__(self, "confidence", _bounded(self.confidence, "confidence"))
        object.__setattr__(self, "novelty", _bounded(self.novelty, "novelty"))
        object.__setattr__(self, "event_risk", _bounded(self.event_risk, "event_risk"))
        object.__setattr__(self, "evidence_ids", tuple(sorted({str(item).strip() for item in self.evidence_ids if str(item).strip()})))
        dimensions = tuple(sorted(self.dimensions, key=lambda item: item.name))
        duplicate_dimensions = _duplicates(item.name for item in dimensions)
        if duplicate_dimensions:
            raise ValueError(f"duplicate context dimensions: {sorted(duplicate_dimensions)}")
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "summary", str(self.summary or "").strip())


@dataclass(frozen=True, slots=True)
class ContextSnapshotV2:
    snapshot_id: str
    as_of: str
    contract_version: str
    engine_version: str
    scope_key: str
    freshness_status: str
    coverage_start: str
    coverage_end: str
    evidence: tuple[ContextEvidenceRefV2, ...]
    targets: tuple[ContextTargetStateV2, ...]
    regime_label: str = ""
    summary: str = ""
    state_fingerprint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _non_empty(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "as_of", _iso_utc(self.as_of))
        object.__setattr__(self, "contract_version", _non_empty(self.contract_version, "contract_version"))
        object.__setattr__(self, "engine_version", _non_empty(self.engine_version, "engine_version"))
        object.__setattr__(self, "scope_key", _non_empty(self.scope_key, "scope_key"))
        if self.freshness_status not in {FRESH, STALE, UNKNOWN}:
            raise ValueError("freshness_status must be FRESH, STALE or UNKNOWN")
        if self.coverage_start:
            object.__setattr__(self, "coverage_start", _iso_utc(self.coverage_start))
        if self.coverage_end:
            object.__setattr__(self, "coverage_end", _iso_utc(self.coverage_end))

        evidence = tuple(sorted(self.evidence, key=lambda item: item.evidence_id))
        duplicate_evidence = _duplicates(item.evidence_id for item in evidence)
        if duplicate_evidence:
            raise ValueError(f"duplicate evidence ids: {sorted(duplicate_evidence)}")
        object.__setattr__(self, "evidence", evidence)

        targets = tuple(sorted(self.targets, key=lambda item: item.target_key))
        duplicate_targets = _duplicates(item.target_key for item in targets)
        if duplicate_targets:
            raise ValueError(f"duplicate target keys: {sorted(duplicate_targets)}")
        object.__setattr__(self, "targets", targets)

        available_evidence = {item.evidence_id for item in evidence}
        referenced_evidence: set[str] = set()
        for target in targets:
            referenced_evidence.update(target.evidence_ids)
            for dimension in target.dimensions:
                referenced_evidence.update(dimension.evidence_ids)
        missing_evidence = referenced_evidence - available_evidence
        if missing_evidence:
            raise ValueError(f"unknown evidence ids referenced by context state: {sorted(missing_evidence)}")

        object.__setattr__(self, "regime_label", str(self.regime_label or "").strip())
        object.__setattr__(self, "summary", str(self.summary or "").strip())
        calculated = context_state_fingerprint_v2(self)
        if self.state_fingerprint and self.state_fingerprint != calculated:
            raise ValueError("state_fingerprint does not match semantic snapshot state")
        object.__setattr__(self, "state_fingerprint", calculated)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _semantic_target_record(target: ContextTargetStateV2) -> dict[str, Any]:
    return {
        "target_key": target.target_key,
        "directional_bias": target.directional_bias,
        "confidence": target.confidence,
        "novelty": target.novelty,
        "event_risk": target.event_risk,
        "evidence_ids": list(target.evidence_ids),
        "dimensions": [asdict(item) for item in target.dimensions],
    }


def _semantic_record(snapshot: ContextSnapshotV2) -> dict[str, Any]:
    """Fields that define semantic state for material-change detection.

    Poll identity (`snapshot_id`, `as_of`) and generated prose summaries are
    deliberately excluded. This prevents timestamp churn or harmless LLM wording
    changes from creating a new canonical semantic state. Freshness and coverage
    remain included because crossing those boundaries is material.
    """

    return {
        "contract_version": snapshot.contract_version,
        "engine_version": snapshot.engine_version,
        "scope_key": snapshot.scope_key,
        "freshness_status": snapshot.freshness_status,
        "coverage_start": snapshot.coverage_start,
        "coverage_end": snapshot.coverage_end,
        "evidence": [asdict(item) for item in snapshot.evidence],
        "targets": [_semantic_target_record(item) for item in snapshot.targets],
        "regime_label": snapshot.regime_label,
    }


def context_state_fingerprint_v2(snapshot: ContextSnapshotV2) -> str:
    payload = json.dumps(_semantic_record(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def materially_changed_v2(previous: ContextSnapshotV2 | None, current: ContextSnapshotV2) -> bool:
    return previous is None or previous.state_fingerprint != current.state_fingerprint


def build_context_snapshot_v2(
    *,
    as_of: str,
    engine_version: str,
    scope_key: str,
    freshness_status: str,
    evidence: Iterable[ContextEvidenceRefV2],
    targets: Iterable[ContextTargetStateV2],
    coverage_start: str = "",
    coverage_end: str = "",
    regime_label: str = "",
    summary: str = "",
) -> ContextSnapshotV2:
    evidence_tuple = tuple(evidence)
    targets_tuple = tuple(targets)
    provisional = ContextSnapshotV2(
        snapshot_id="provisional",
        as_of=as_of,
        contract_version=CONTEXT_CONTRACT_VERSION,
        engine_version=engine_version,
        scope_key=scope_key,
        freshness_status=freshness_status,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        evidence=evidence_tuple,
        targets=targets_tuple,
        regime_label=regime_label,
        summary=summary,
    )
    identity = uuid5(
        NAMESPACE_URL,
        f"pricegauger:{CONTEXT_CONTRACT_VERSION}:{scope_key}:{provisional.as_of}:{provisional.state_fingerprint}",
    )
    return ContextSnapshotV2(
        snapshot_id=str(identity),
        as_of=provisional.as_of,
        contract_version=provisional.contract_version,
        engine_version=provisional.engine_version,
        scope_key=provisional.scope_key,
        freshness_status=provisional.freshness_status,
        coverage_start=provisional.coverage_start,
        coverage_end=provisional.coverage_end,
        evidence=provisional.evidence,
        targets=provisional.targets,
        regime_label=provisional.regime_label,
        summary=provisional.summary,
        state_fingerprint=provisional.state_fingerprint,
    )
