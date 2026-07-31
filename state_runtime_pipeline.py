from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from market_state_store import MarketStateStore
from notification_service import (
    NotificationConfig,
    NotificationStore,
    configured_notifiers,
    dispatch_market_mover,
    should_notify,
)
from state_runtime_service import (
    build_decision_states,
    build_information_state,
    contributions_from_posts,
    detect_alerts,
)
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment


LOGGER = logging.getLogger("pricegauger.state_runtime")
DEFAULT_STATE_HEARTBEAT_SECONDS = 15 * 60


def _heartbeat_seconds() -> int:
    raw = os.getenv("PRICEGAUGER_STATE_HEARTBEAT_SECONDS", str(DEFAULT_STATE_HEARTBEAT_SECONDS)).strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_STATE_HEARTBEAT_SECONDS


def _heartbeat_due(latest: dict | None, *, now: datetime | None = None) -> bool:
    if latest is None:
        return True
    value = str(latest.get("as_of") or "").strip()
    if not value:
        return True
    try:
        recorded = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current.astimezone(timezone.utc) - recorded.astimezone(timezone.utc)).total_seconds() >= _heartbeat_seconds()


def process_flow_snapshot(
    *,
    db_path: str | Path,
    assessment: TelegramFlowAssessment,
    posts: list[ScoredTelegramPost],
) -> None:
    """Persist authoritative state updates and dispatch alerts for newly evaluated event contributions."""
    runtime_store = StateRuntimeStore(db_path)

    new_posts: list[ScoredTelegramPost] = []
    for post in posts:
        if any(
            not runtime_store.has_contribution(event_id=post.message_id, market=score.asset)
            for score in post.scores
        ):
            new_posts.append(post)

    latest_information = runtime_store.load_latest_information_state()
    heartbeat_due = _heartbeat_due(latest_information)
    if not new_posts and not heartbeat_due:
        LOGGER.info(
            "state runtime skipped reason=no_material_change heartbeat_seconds=%s",
            _heartbeat_seconds(),
        )
        return

    interpretations = MarketStateStore(db_path).load_interpretations()
    information = build_information_state(assessment, interpretations)
    runtime_store.save_information_state(information)

    previous = {
        item.asset: runtime_store.load_latest_decision_state(market=item.asset)
        for item in assessment.assets
    }
    decisions = build_decision_states(assessment, information, previous=previous)
    runtime_store.save_decision_states(decisions)

    if not new_posts:
        LOGGER.info(
            "state runtime heartbeat information=%s decisions=%s new_posts=0 alerts=0",
            information.snapshot_id,
            len(decisions),
        )
        return

    contributions = contributions_from_posts(new_posts)
    runtime_store.save_contributions(contributions)
    alerts = detect_alerts(new_posts, information)
    delivery_store = NotificationStore(db_path)
    notification_config = NotificationConfig.from_env()
    notifiers = configured_notifiers(notification_config)
    for alert in alerts:
        runtime_store.save_alert(alert)
        results = dispatch_market_mover(
            alert,
            config=notification_config,
            store=delivery_store,
            notifiers=notifiers,
        )
        delivered = sum(item.delivered and item.detail != "duplicate skipped" for item in results)
        failed = sum(not item.delivered for item in results)
        if not should_notify(alert, minimum_severity=notification_config.minimum_severity):
            delivery_status = "filtered"
        elif not notifiers:
            delivery_status = "unconfigured"
        elif delivered:
            delivery_status = "delivered"
        elif results and all(item.detail == "duplicate skipped" for item in results):
            delivery_status = "duplicate"
        else:
            delivery_status = "failed"
        LOGGER.info(
            "market mover alert=%s severity=%s market=%s delivery_status=%s deliveries=%s failures=%s",
            alert.alert_id,
            alert.severity,
            alert.market,
            delivery_status,
            delivered,
            failed,
        )

    LOGGER.info(
        "state runtime updated information=%s decisions=%s new_posts=%s contributions=%s alerts=%s",
        information.snapshot_id,
        len(decisions),
        len(new_posts),
        len(contributions),
        len(alerts),
    )
