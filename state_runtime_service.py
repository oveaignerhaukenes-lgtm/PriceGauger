from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

from market_interpretation import MarketInterpretation
from state_contracts import (
    ComponentStatus,
    EventContribution,
    InformationStateSnapshot,
    MarketMoverAlert,
    MarketStateSnapshot,
    detect_market_mover,
)
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment


ENGINE_VERSION = "state-runtime-v1"
_MOVE_SCALE = {
    "Brent": 5.0,
    "Gold": 2.5,
    "Silver": 4.0,
    "DXY": 1.5,
    "Natural Gas": 6.0,
}


def _stable_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _utc_now(value: datetime | None = None) -> datetime:
    now = value or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def build_information_state(
    flow: TelegramFlowAssessment,
    interpretations: Iterable[MarketInterpretation],
    *,
    as_of: datetime | None = None,
) -> InformationStateSnapshot:
    now = _utc_now(as_of)
    rows = list(interpretations)
    recent = []
    for item in rows:
        published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
        if (now - published.astimezone(timezone.utc)).total_seconds() <= 12 * 3600:
            recent.append(item)

    latest = recent[-1] if recent else None
    recent_types = [item.update_type for item in recent]
    ceasefire_active = bool(
        latest
        and latest.update_type == "DEESCALATION"
        and any(token in latest.summary.lower() for token in ("ceasefire", "truce", "våpenhvile"))
    )
    if ceasefire_active:
        regime = "CEASEFIRE"
    elif recent_types.count("ESCALATION") >= 3:
        regime = "HIGH_INTENSITY_WAR"
    elif "ESCALATION" in recent_types:
        regime = "ACTIVE_WAR"
    elif "DEESCALATION" in recent_types:
        regime = "DEESCALATING"
    else:
        regime = "CALM" if not recent else "MIXED"

    active_clusters = {item.cluster_id for item in recent if item.update_type not in {"DUPLICATE", "CONTEXT"}}
    saturation = min(1.0, max(0.0, (flow.post_count - flow.event_cluster_count) / max(flow.post_count, 1)))
    confirmation_rows = [item for item in recent if item.update_type in {"CONFIRMATION", "UPDATE"}]
    confirmation_quality = (
        sum(item.confidence * item.source_quality for item in confirmation_rows) / len(confirmation_rows)
        if confirmation_rows
        else 0.35
    )
    supply_rows = [item for item in recent if item.state_deltas.get("energy_supply_risk", 0.0) > 0]
    supply_risk = min(
        1.0,
        sum(
            item.state_deltas["energy_supply_risk"] * item.confidence * item.source_quality
            for item in supply_rows
        ),
    )
    component = ComponentStatus(
        observed_at=flow.as_of,
        age_seconds=max(0, int((now - datetime.fromisoformat(flow.as_of.replace("Z", "+00:00"))).total_seconds())),
        freshness="FRESH",
        provider="telegram-flow+market-interpretations",
        instrument="selected-markets",
        engine_version=ENGINE_VERSION,
    )
    payload = {"as_of": now.isoformat(), "flow_as_of": flow.as_of, "clusters": flow.event_cluster_count, "regime": regime}
    return InformationStateSnapshot(
        snapshot_id=_stable_id("information-state", payload),
        as_of=now.isoformat(),
        event_cluster_count=flow.event_cluster_count,
        active_event_count=len(active_clusters),
        conflict_regime=regime,
        ceasefire_active=ceasefire_active,
        narrative_saturation=round(saturation, 4),
        confirmation_quality=round(max(0.0, min(1.0, confirmation_quality)), 4),
        supply_risk=round(max(0.0, min(1.0, supply_risk)), 4),
        source_channels=flow.source_channels,
        component=component,
    )


def contributions_from_posts(posts: Iterable[ScoredTelegramPost]) -> list[EventContribution]:
    results: list[EventContribution] = []
    for post in posts:
        for score in post.scores:
            direction_nudge = (
                score.direction
                * score.impact
                * score.confidence
                * post.novelty
                * post.source_quality
            )
            high = _MOVE_SCALE.get(score.asset, 3.0) * abs(score.direction) * score.impact
            signed_high = high if score.direction >= 0 else -high
            signed_low = signed_high * 0.35
            results.append(
                EventContribution(
                    event_id=str(post.message_id),
                    event_cluster_id=post.event_key,
                    market=score.asset,
                    observed_at=post.published_at,
                    direction_nudge=direction_nudge,
                    confidence_nudge=score.confidence * post.source_quality,
                    expected_move_low_pct=round(signed_low, 4),
                    expected_move_high_pct=round(signed_high, 4),
                    horizon_hours=score.horizon_hours,
                    novelty=post.novelty,
                    source_quality=post.source_quality,
                    confirmation_status=(
                        "CONFIRMED" if post.relation in {"confirmation", "update"} else "UNCONFIRMED"
                    ),
                    rationale=score.rationale,
                )
            )
    return results


def detect_alerts(
    posts: Iterable[ScoredTelegramPost],
    information: InformationStateSnapshot,
) -> list[MarketMoverAlert]:
    post_by_id = {str(item.message_id): item for item in posts}
    alerts: list[MarketMoverAlert] = []
    for contribution in contributions_from_posts(post_by_id.values()):
        post = post_by_id[contribution.event_id]
        market_state = MarketStateSnapshot(
            snapshot_id=f"pending-market:{contribution.market}:{contribution.event_id}",
            market=contribution.market,
            as_of=contribution.observed_at,
            price=None,
            direction_score=0.0,
            volatility_score=0.0,
            momentum_score=0.0,
            price_confirmation=0.0,
            regime="PRICE_CONFIRMATION_PENDING",
            component=ComponentStatus(
                observed_at=contribution.observed_at,
                age_seconds=0,
                freshness="MISSING",
                provider="pending-market-data",
                instrument=contribution.market,
                engine_version=ENGINE_VERSION,
            ),
        )
        alert = detect_market_mover(
            contribution,
            information,
            market_state,
            headline=post.text.splitlines()[0][:180] if post.text.strip() else "Potential market mover",
            summary=contribution.rationale,
        )
        if alert is not None:
            alerts.append(replace(alert, updated_at=information.as_of))
    return alerts
