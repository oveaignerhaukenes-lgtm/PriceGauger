from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from database import connect


CONTEXT_SOURCE_POLICY_VERSION = "context-source-policy-v2.0"


def _non_empty(value: str, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ContextSourceKeyV2:
    """Stable source identity independent of how the source is currently used."""

    source_kind: str
    source_id: str
    source_scope: str = "GLOBAL_SHARED"
    user_scope_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", _non_empty(self.source_kind, "source_kind"))
        object.__setattr__(self, "source_id", _non_empty(self.source_id, "source_id"))
        if self.source_scope not in {"GLOBAL_SHARED", "USER_SCOPED"}:
            raise ValueError("source_scope must be GLOBAL_SHARED or USER_SCOPED")
        user_scope_id = str(self.user_scope_id or "").strip()
        if self.source_scope == "USER_SCOPED" and not user_scope_id:
            raise ValueError("USER_SCOPED source requires user_scope_id")
        if self.source_scope == "GLOBAL_SHARED" and user_scope_id:
            raise ValueError("GLOBAL_SHARED source cannot carry user_scope_id")
        object.__setattr__(self, "user_scope_id", user_scope_id)

    @property
    def source_key(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextSourcePolicyV2:
    """Four independent user/product policy axes for one Context source.

    exposure_enabled: source may be fetched/observed and shown in diagnostics.
    composition_enabled: source may contribute to a composed Context state.
    identity_enabled: source is considered part of the user's persistent worldview/profile.
    learning_enabled: observations involving the source may enter future learning datasets.

    AP12 stores policy only. No learning, composition or ingestion runtime consumes it yet.
    """

    source: ContextSourceKeyV2
    exposure_enabled: bool = True
    composition_enabled: bool = False
    identity_enabled: bool = False
    learning_enabled: bool = False
    policy_version: str = CONTEXT_SOURCE_POLICY_VERSION
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_version", _non_empty(self.policy_version, "policy_version"))
        object.__setattr__(self, "updated_at", str(self.updated_at or "").strip())

    def to_record(self) -> dict:
        record = asdict(self)
        record["source_key"] = self.source.source_key
        return record

    def with_changes(self, **changes: bool) -> "ContextSourcePolicyV2":
        allowed = {
            "exposure_enabled",
            "composition_enabled",
            "identity_enabled",
            "learning_enabled",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported policy fields: {sorted(unknown)}")
        normalized = {key: bool(value) for key, value in changes.items()}
        return replace(self, **normalized, updated_at=_utc_now())


class ContextSourcePolicyStoreV2:
    """Persistence boundary for source policy metadata only."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS context_v2_source_policies (
                    source_key TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_scope TEXT NOT NULL,
                    user_scope_id TEXT NOT NULL DEFAULT '',
                    exposure_enabled INTEGER NOT NULL,
                    composition_enabled INTEGER NOT NULL,
                    identity_enabled INTEGER NOT NULL,
                    learning_enabled INTEGER NOT NULL,
                    policy_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_kind, source_id, source_scope, user_scope_id)
                );
                """
            )

    def load(self, source: ContextSourceKeyV2) -> ContextSourcePolicyV2:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT * FROM context_v2_source_policies WHERE source_key=?",
                (source.source_key,),
            ).fetchone()
        if row is None:
            return ContextSourcePolicyV2(source=source)
        return ContextSourcePolicyV2(
            source=source,
            exposure_enabled=bool(row["exposure_enabled"]),
            composition_enabled=bool(row["composition_enabled"]),
            identity_enabled=bool(row["identity_enabled"]),
            learning_enabled=bool(row["learning_enabled"]),
            policy_version=str(row["policy_version"]),
            updated_at=str(row["updated_at"]),
        )

    def save(self, policy: ContextSourcePolicyV2) -> None:
        updated_at = policy.updated_at or _utc_now()
        source = policy.source
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO context_v2_source_policies(
                    source_key, source_kind, source_id, source_scope, user_scope_id,
                    exposure_enabled, composition_enabled, identity_enabled,
                    learning_enabled, policy_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    exposure_enabled=excluded.exposure_enabled,
                    composition_enabled=excluded.composition_enabled,
                    identity_enabled=excluded.identity_enabled,
                    learning_enabled=excluded.learning_enabled,
                    policy_version=excluded.policy_version,
                    updated_at=excluded.updated_at
                """,
                (
                    source.source_key,
                    source.source_kind,
                    source.source_id,
                    source.source_scope,
                    source.user_scope_id,
                    int(policy.exposure_enabled),
                    int(policy.composition_enabled),
                    int(policy.identity_enabled),
                    int(policy.learning_enabled),
                    policy.policy_version,
                    updated_at,
                ),
            )

    def list_all(self) -> tuple[ContextSourcePolicyV2, ...]:
        with connect(self.path) as db:
            rows = db.execute(
                """
                SELECT source_kind, source_id, source_scope, user_scope_id,
                       exposure_enabled, composition_enabled, identity_enabled,
                       learning_enabled, policy_version, updated_at
                FROM context_v2_source_policies
                ORDER BY source_scope, source_kind, source_id, user_scope_id
                """
            ).fetchall()
        result = []
        for row in rows:
            source = ContextSourceKeyV2(
                source_kind=str(row["source_kind"]),
                source_id=str(row["source_id"]),
                source_scope=str(row["source_scope"]),
                user_scope_id=str(row["user_scope_id"]),
            )
            result.append(
                ContextSourcePolicyV2(
                    source=source,
                    exposure_enabled=bool(row["exposure_enabled"]),
                    composition_enabled=bool(row["composition_enabled"]),
                    identity_enabled=bool(row["identity_enabled"]),
                    learning_enabled=bool(row["learning_enabled"]),
                    policy_version=str(row["policy_version"]),
                    updated_at=str(row["updated_at"]),
                )
            )
        return tuple(result)
