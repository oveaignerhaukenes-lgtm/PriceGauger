from __future__ import annotations

import logging
from pathlib import Path

from market_state_store import MarketStateStore
from notification_service import NotificationStore, dispatch_market_mover
from state_runtime_service import (
    build_decision_states,
    build_information_state,
    contributions_from_posts,
    detect_alerts,
)
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment


LOGGER = logging.getLogger("pricegauger.state_runtime")


def process_flow_snapshot(
    *,
    db_path: str | Path,
    assessment: TelegramFlowAssessment,
    posts: list[ScoredTelegramPost],
) -> None:
    """Persist authoritative state updates and dispatch alerts for newly evaluated event contributions."""
    runtime_store = StateRuntimeStore(db_path)
    interpretations = MarketStateStore(db_path).load_interpretations()
    information = build_information_state(assessment, interpretations)
    runtime_store.save_information_state(information)

    previous = {
        item.asset: runtime_store.load_latest_decision_state(market=item.asset)
        for item in assessment.assets
    }
    decisions = build_decision_states(assessment, information, previous=previous)
    runtime_store.save_decision_states(decisions)

    new_posts: list[ScoredTelegramPost] = []
    for post in posts:
        if any(
            not runtime_store.has_contribution(event_id=post.message_id, market=score.asset)
            for score in post.scores
        ):
            new_posts.append(post)

    if not new_posts:
        LOGGER.info(
            "state runtime updated information=%s decisions=%s new_posts=0 alerts=0",
            information.snapshot_id,
            len(decisions),
        )
        return

    contributions = contributions_from_posts(new_posts)
    runtime_store.save_contributions(contributions)
    alerts = detect_alerts(new_posts, information)
    delivery_store = NotificationStore(db_path)
    for alert in alerts:
        runtime_store.save_alert(alert)
        results = dispatch_market_mover(alert, store=delivery_store)
        delivered = sum(item.delivered and item.detail != "duplicate skipped" for item in results)
        LOGGER.info(
            "market mover alert=%s severity=%s market=%s deliveries=%s",
            alert.alert_id,
            alert.severity,
            alert.market,
            delivered,
        )

    LOGGER.info(
        "state runtime updated information=%s decisions=%s new_posts=%s contributions=%s alerts=%s",
        information.snapshot_id,
        len(decisions),
        len(new_posts),
        len(contributions),
        len(alerts),
    )
