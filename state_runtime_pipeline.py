from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from analysis_status import AnalysisStatusStore
from config import twelve_data_api_key
from market_data import TwelveDataProvider, fetch_market_data
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
from saxo_provider import SaxoPriceProvider
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment
from technical_state_runtime import build_technical_market_states
from worker_probe import record_worker_probe


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


def _refresh_overview_summary(*, db_path: str | Path, information_snapshot_id: str, as_of: str) -> None:
    try:
        from overview_ai_summary import build_overview_summary
        from overview_service import load_overview
        from overview_summary_store import OverviewSummaryStore

        data = load_overview(db_path)
        summary = build_overview_summary(data, prefer_persisted=False)
        OverviewSummaryStore(db_path).save(
            information_snapshot_id=information_snapshot_id,
            as_of=as_of,
            summary=summary,
        )
        LOGGER.info(
            "overview summary persisted information=%s model=%s",
            information_snapshot_id,
            summary.model,
        )
    except Exception:
        LOGGER.exception("overview summary generation failed; persisted market state remains available")


def process_flow_snapshot(
    *,
    db_path: str | Path,
    assessment: TelegramFlowAssessment,
    posts: list[ScoredTelegramPost],
) -> None:
    """Persist authoritative state updates and dispatch alerts for newly evaluated event contributions."""
    probe = record_worker_probe(db_path, component="state-runtime", cycle_status="active")
    LOGGER.info(
        "state runtime probe heartbeat=%s database_identity=%s",
        probe.heartbeat_at,
        probe.database_identity,
    )
    runtime_store = StateRuntimeStore(db_path)
    status_store = AnalysisStatusStore(db_path)

    new_posts: list[ScoredTelegramPost] = []
    for post in posts:
        if any(
            not runtime_store.has_contribution(event_id=post.message_id, market=score.asset)
            for score in post.scores
        ):
            new_posts.append(post)

    latest_information = runtime_store.load_latest_information_state()
    heartbeat_due = _heartbeat_due(latest_information)
    saxo = SaxoPriceProvider()
    providers = [saxo] if saxo.client is not None and saxo.instruments else []
    twelve_key = twelve_data_api_key()
    if twelve_key:
        providers.append(TwelveDataProvider(twelve_key))
    missing_decisions = [
        item.asset
        for item in assessment.assets
        if runtime_store.load_latest_decision_state(market=item.asset) is None
    ]
    missing_market_states = [
        item.asset
        for item in assessment.assets
        if providers and runtime_store.load_latest_market_state(market=item.asset) is None
    ]
    if not new_posts and not heartbeat_due and not missing_decisions and not missing_market_states:
        try:
            from overview_summary_store import OverviewSummaryStore

            summary_missing = OverviewSummaryStore(db_path).load_latest() is None
        except Exception:
            summary_missing = True
        if summary_missing and latest_information is not None:
            _refresh_overview_summary(
                db_path=db_path,
                information_snapshot_id=str(latest_information.get("snapshot_id") or "legacy-state"),
                as_of=str(latest_information.get("as_of") or assessment.as_of),
            )
        LOGGER.info(
            "state runtime skipped reason=no_material_change heartbeat_seconds=%s",
            _heartbeat_seconds(),
        )
        return

    interpretations = MarketStateStore(db_path).load_interpretations()
    previous_information = runtime_store.load_latest_information_snapshot()
    information = build_information_state(
        assessment,
        interpretations,
        previous=previous_information,
    )
    runtime_store.save_information_state(information)

    previous = {
        item.asset: runtime_store.load_latest_decision_state(market=item.asset)
        for item in assessment.assets
    }
    status_store.running("technical_state", "Henter prisbarer og bygger flertidsrammeregime.")
    if providers:
        def fetcher(request):
            return fetch_market_data(request, providers)

        market_states, technical_errors = build_technical_market_states(
            [item.asset for item in assessment.assets], fetcher=fetcher
        )
    else:
        market_states, technical_errors = {}, {}
    runtime_store.save_market_states(market_states.values())
    if market_states:
        detail = f"{len(market_states)} markeder oppdatert fra pris og teknisk regime."
        if technical_errors:
            detail += f" {len(technical_errors)} marked(er) manglet data."
        status_store.complete("technical_state", detail)
    elif technical_errors:
        detail = "; ".join(f"{market}: {error}" for market, error in technical_errors.items())
        status_store.failed("technical_state", detail or "Ingen markedsdata tilgjengelig.")
    else:
        status_store.skipped("technical_state", "Saxo/Twelve Data er ikke konfigurert for workeren.")

    decisions = build_decision_states(
        assessment, information, previous=previous, market_states=market_states
    )
    runtime_store.save_decision_states(decisions)

    if missing_decisions:
        LOGGER.info(
            "state runtime bootstrapped missing_decisions=%s",
            ",".join(missing_decisions),
        )
    if missing_market_states:
        LOGGER.info(
            "state runtime bootstrapped missing_market_states=%s",
            ",".join(missing_market_states),
        )

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

    _refresh_overview_summary(
        db_path=db_path,
        information_snapshot_id=information.snapshot_id,
        as_of=information.as_of,
    )
    LOGGER.info(
        "state runtime updated information=%s decisions=%s new_posts=%s contributions=%s alerts=%s",
        information.snapshot_id,
        len(decisions),
        len(new_posts),
        len(contributions),
        len(alerts),
    )
