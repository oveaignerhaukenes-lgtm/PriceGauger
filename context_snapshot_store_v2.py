from __future__ import annotations

import json
from pathlib import Path

from context_snapshot_v2 import (
    ContextDimensionV2,
    ContextEvidenceRefV2,
    ContextSnapshotV2,
    ContextTargetStateV2,
    materially_changed_v2,
)
from database import connect


class ContextSnapshotStoreV2:
    """Canonical Context-v2 semantic-state persistence.

    Raw evidence may update frequently. This store appends a canonical snapshot only
    when semantic state materially changes. It has no legacy Decision/Recommendation,
    Technical Core, Composer, LLM, or execution side effects.
    """

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS context_v2_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    contract_version TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    freshness_status TEXT NOT NULL,
                    state_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(scope_key, state_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_context_v2_scope_as_of
                    ON context_v2_snapshots(scope_key, as_of DESC);
                """
            )

    def _connect(self):
        return connect(self.path)

    def load_latest(self, *, scope_key: str = "global") -> ContextSnapshotV2 | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM context_v2_snapshots
                WHERE scope_key=?
                ORDER BY as_of DESC, recorded_at DESC
                LIMIT 1
                """,
                (scope_key,),
            ).fetchone()
        if row is None:
            return None
        return context_snapshot_v2_from_record(json.loads(row["payload_json"]))

    def save_if_material_change(self, snapshot: ContextSnapshotV2) -> bool:
        """Persist snapshot iff its semantic state differs from the latest scope state."""
        previous = self.load_latest(scope_key=snapshot.scope_key)
        if not materially_changed_v2(previous, snapshot):
            return False

        payload = json.dumps(snapshot.to_record(), ensure_ascii=False, sort_keys=True)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO context_v2_snapshots(
                    snapshot_id, scope_key, as_of, contract_version, engine_version,
                    freshness_status, state_fingerprint, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key, state_fingerprint) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.scope_key,
                    snapshot.as_of,
                    snapshot.contract_version,
                    snapshot.engine_version,
                    snapshot.freshness_status,
                    snapshot.state_fingerprint,
                    payload,
                ),
            )
        return True


def context_snapshot_v2_from_record(record: dict) -> ContextSnapshotV2:
    evidence = tuple(ContextEvidenceRefV2(**item) for item in record.get("evidence") or ())
    targets: list[ContextTargetStateV2] = []
    for item in record.get("targets") or ():
        target = dict(item)
        target["evidence_ids"] = tuple(target.get("evidence_ids") or ())
        target["dimensions"] = tuple(
            ContextDimensionV2(
                **{
                    **dimension,
                    "evidence_ids": tuple(dimension.get("evidence_ids") or ()),
                }
            )
            for dimension in target.get("dimensions") or ()
        )
        targets.append(ContextTargetStateV2(**target))

    payload = dict(record)
    payload["evidence"] = evidence
    payload["targets"] = tuple(targets)
    return ContextSnapshotV2(**payload)
