from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from analysis_status import AnalysisStatusStore
from database import connect
from telegram_content_filter import classify_telegram_content
from telegram_flow_engine import (
    AssetFlowAssessment,
    AssetPostScore,
    FlowContribution,
    ScoredTelegramPost,
    TelegramFlowAssessment,
)


LOGGER = logging.getLogger("pricegauger.telegram_flow_store")


class TelegramFlowStore:
    """Persistent Telegram Flow storage shared by SQLite and PostgreSQL."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_flow_posts (
                    message_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS telegram_flow_snapshots (
                    as_of TEXT PRIMARY KEY,
                    engine_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def _status(self) -> AnalysisStatusStore:
        return AnalysisStatusStore(self.path)

    def save_posts(self, posts: Iterable[ScoredTelegramPost]) -> int:
        rows = list(posts)
        if not rows:
            return 0
        status = self._status()
        status.running("telegram_scoring", f"Lagrer {len(rows)} AI-vurderte poster.")
        with self._connect() as db:
            for item in rows:
                db.execute(
                    """
                    INSERT INTO telegram_flow_posts(
                        message_id, channel, published_at, event_key, relation, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        channel=excluded.channel,
                        published_at=excluded.published_at,
                        event_key=excluded.event_key,
                        relation=excluded.relation,
                        payload_json=excluded.payload_json,
                        scored_at=CURRENT_TIMESTAMP
                    """,
                    (
                        item.message_id,
                        item.channel,
                        item.published_at,
                        item.event_key,
                        item.relation,
                        json.dumps(item.to_record(), ensure_ascii=False, sort_keys=True),
                    ),
                )
        status.complete("telegram_fetch", f"{len(rows)} nye poster hentet og mottatt av analyseflyten.")
        status.complete("telegram_scoring", f"{len(rows)} poster AI-vurdert og lagret.")
        return len(rows)

    def has_post(self, message_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 AS present FROM telegram_flow_posts WHERE message_id=?",
                (str(message_id),),
            ).fetchone()
        return row is not None

    def load_posts(
        self,
        *,
        limit: int = 500,
        include_filtered: bool = False,
    ) -> list[ScoredTelegramPost]:
        """Load scored posts, excluding promotional recruitment by default.

        Filtered posts remain in persistent storage for diagnostics and audit. Pass
        ``include_filtered=True`` only from development tooling that explicitly
        needs to inspect rejected content.
        """
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM telegram_flow_posts
                ORDER BY published_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        posts = [_post_from_record(json.loads(row["payload_json"])) for row in reversed(rows)]
        if include_filtered:
            return posts

        accepted: list[ScoredTelegramPost] = []
        rejected = 0
        for post in posts:
            eligibility = classify_telegram_content(post.text)
            if eligibility.eligible:
                accepted.append(post)
            else:
                rejected += 1
                LOGGER.info(
                    "telegram post filtered message_id=%s channel=%s reason=%s promotional_score=%.2f",
                    post.message_id,
                    post.channel,
                    eligibility.reason,
                    eligibility.promotional_score,
                )
        self._status().complete(
            "semantic_filter",
            f"{len(accepted)} poster godkjent; {rejected} promo-/rekrutteringsposter filtrert.",
        )
        return accepted

    def save_snapshot(self, assessment: TelegramFlowAssessment) -> None:
        status = self._status()
        status.running("event_clustering", "Oppdaterer hendelsesklynger og samlet Telegram Flow.")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_flow_snapshots(as_of, engine_version, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(as_of) DO UPDATE SET
                    engine_version=excluded.engine_version,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (
                    assessment.as_of,
                    assessment.engine_version,
                    json.dumps(assessment.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )
        status.complete(
            "event_clustering",
            f"{assessment.post_count} poster redusert til {assessment.event_cluster_count} hendelsesklynger.",
        )

        # State processing is downstream of the persisted flow snapshot. Failures are
        # isolated so Telegram Flow remains available even when an alert provider fails.
        try:
            from state_runtime_pipeline import process_flow_snapshot

            status.running("information_state", "Bygger samlet Information State.")
            status.running("decision_state", "Oppdaterer Decision State per marked.")
            status.running("recommendation", "Avventer oppdatert Decision State.")
            process_flow_snapshot(
                db_path=self.path,
                assessment=assessment,
                posts=self.load_posts(limit=500),
            )
            status.complete("information_state", "Information State oppdatert fra siste autoritative flow-snapshot.")
            status.complete("decision_state", "Decision State oppdatert for alle tilgjengelige markeder.")
            status.complete("recommendation", "Foreløpige anbefalinger regenerert fra siste Decision State.")
        except Exception as exc:
            status.failed("information_state", str(exc))
            status.failed("decision_state", str(exc))
            status.failed("recommendation", "Ingen ny anbefaling fordi state runtime feilet.")
            LOGGER.exception("state runtime processing failed after Telegram flow snapshot")

    def load_latest_snapshot(self) -> TelegramFlowAssessment | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM telegram_flow_snapshots
                ORDER BY as_of DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return _assessment_from_record(json.loads(row["payload_json"]))


def _post_from_record(record: dict) -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id=str(record.get("message_id") or ""),
        channel=str(record.get("channel") or ""),
        published_at=str(record.get("published_at") or ""),
        text=str(record.get("text") or ""),
        event_key=str(record.get("event_key") or ""),
        relation=str(record.get("relation") or "new"),
        novelty=float(record.get("novelty") or 0.0),
        source_quality=float(record.get("source_quality") or 0.0),
        scores=tuple(AssetPostScore(**item) for item in record.get("scores") or []),
    )


def _assessment_from_record(record: dict) -> TelegramFlowAssessment:
    return TelegramFlowAssessment(
        as_of=str(record.get("as_of") or ""),
        engine_version=str(record.get("engine_version") or ""),
        source_channels=tuple(record.get("source_channels") or ()),
        post_count=int(record.get("post_count") or 0),
        event_cluster_count=int(record.get("event_cluster_count") or 0),
        assets=tuple(AssetFlowAssessment(**item) for item in record.get("assets") or []),
        contributions=tuple(FlowContribution(**item) for item in record.get("contributions") or []),
        model=str(record.get("model") or ""),
    )
