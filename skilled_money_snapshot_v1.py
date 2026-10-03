from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


EvidenceKind = Literal["OBSERVED", "INFERRED", "CONFIRMED", "WEAKENED", "REFUTED"]


@dataclass(frozen=True)
class SkilledMoneyEvidenceV1:
    label: str
    statement: str
    kind: EvidenceKind
    confidence: float | None = None
    source: str | None = None
    available_at: datetime | None = None


@dataclass(frozen=True)
class SkilledMoneyRevisionV1:
    revision: int
    created_at: datetime
    summary: str
    evidence: tuple[SkilledMoneyEvidenceV1, ...] = ()


@dataclass(frozen=True)
class SkilledMoneySnapshotV1:
    event_id: str
    instrument: str
    event_started_at: datetime
    event_ended_at: datetime | None
    move_summary: str
    technical_regime: dict[str, object] = field(default_factory=dict)
    world_regime: dict[str, object] = field(default_factory=dict)
    actor_state: dict[str, object] = field(default_factory=dict)
    revisions: tuple[SkilledMoneyRevisionV1, ...] = ()

    @property
    def latest_revision(self) -> SkilledMoneyRevisionV1 | None:
        return self.revisions[-1] if self.revisions else None
