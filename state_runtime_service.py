from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Iterable, Mapping

from market_interpretation import MarketInterpretation
from market_interpretation import STATE_NAMES
from asset_state_mapping import ASSET_WEIGHTS
from market_state import interpretation_weight
from state_contracts import (
    ComponentStatus,
    DecisionStateSnapshot,
    EventContribution,
    InformationStateSnapshot,
    MarketMoverAlert,
    MarketStateSnapshot,
    detect_market_mover,
)
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment


ENGINE_VERSION = "state-runtime-v1"
INFORMATION_STATE_HALF_LIFE_HOURS = 6.0
_MOVE_SCALE = {
    "Brent": 5.0,
    "Gold": 2.5,
    "Silver": 4.0,
    "DXY": 1.5,
    "Natural Gas": 6.0,
}

# A raw Telegram-flow contribution is not directly comparable across markets.
# These scales convert aggregate impulse into a bounded directional strength while
# preserving differences between instruments. They are explicit v1 baselines and
# should later be calibrated from realized outcomes rather than changed ad hoc.
_IMPULSE_SCALE = {
    "Brent": 0.20,
    "Gold": 0.16,
    "Silver": 0.20,
    "DXY": 0.08,
    "Natural Gas": 0.25,
}


def _stable_id(prefix: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _utc_now(value: datetime | None = None) -> datetime:
    now = value or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def market_impulse_score(market: str, flow_score: float) -> float:
    """Convert aggregate flow impulse to a bounded, market-specific strength.

    ``normalized_score`` in Telegram Flow expresses directional agreement. It
    reaches ±1 whenever all selected contributions point the same way, even when
    their total market impact is tiny. Decision State instead needs the magnitude
    of the aggregate impulse, so it uses a smooth tanh transform of ``flow_score``.
    """
    scale = max(0.01, float(_IMPULSE_SCALE.get(str(market), 0.20)))
    return max(-1.0, min(1.0, math.tanh(float(flow_score) / scale)))


def build_information_state(
    flow: TelegramFlowAssessment,
    interpretations: Iterable[MarketInterpretation],
    *,
    previous: InformationStateSnapshot | None = None,
    as_of: datetime | None = None,
) -> InformationStateSnapshot:
    now = _utc_now(as_of)
    rows = sorted(interpretations, key=lambda item: item.published_at)
    processed = set(previous.processed_event_ids if previous else ())
    new_rows = [item for item in rows if item.event_id not in processed]

    values = {name: 0.0 for name in STATE_NAMES}
    if previous is not None:
        values.update(previous.state_values or {})
        previous_time = datetime.fromisoformat(previous.as_of.replace("Z", "+00:00"))
        elapsed_hours = max(0.0, (now - previous_time).total_seconds() / 3600.0)
        decay = math.exp(-math.log(2.0) * elapsed_hours / INFORMATION_STATE_HALF_LIFE_HOURS)
        values = {name: float(values[name]) * decay for name in STATE_NAMES}

    state_change = {name: 0.0 for name in STATE_NAMES}
    material_rows: list[MarketInterpretation] = []
    for item in new_rows:
        published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
        age_hours = max(0.0, (now - published.astimezone(timezone.utc)).total_seconds() / 3600.0)
        weight = interpretation_weight(
            item,
            age_hours=age_hours,
            half_life_hours=INFORMATION_STATE_HALF_LIFE_HOURS,
            max_age_hours=24.0,
        )
        if weight:
            material_rows.append(item)
            for name in STATE_NAMES:
                delta = float(item.state_deltas[name]) * weight
                state_change[name] += delta
                values[name] = max(-1.0, min(1.0, values[name] + delta))
        processed.add(item.event_id)

    active_clusters = {
        item.cluster_id
        for item in rows
        if item.update_type not in {"DUPLICATE", "CONTEXT"}
        and 0.0
        <= (now - datetime.fromisoformat(item.published_at.replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds()
        <= 12 * 3600
    }
    latest = material_rows[-1] if material_rows else None
    ceasefire_active = bool(previous.ceasefire_active if previous else False)
    if latest and latest.update_type in {"ESCALATION", "NEW_EVENT"}:
        ceasefire_active = False
    if latest and latest.update_type == "DEESCALATION" and any(
        token in latest.summary.lower() for token in ("ceasefire", "truce", "våpenhvile")
    ):
        ceasefire_active = True

    conflict = values["conflict_pressure"]
    if ceasefire_active:
        regime = "CEASEFIRE"
    elif conflict >= 0.65:
        regime = "HIGH_INTENSITY_WAR"
    elif conflict >= 0.2:
        regime = "ACTIVE_WAR"
    elif conflict <= -0.2:
        regime = "DEESCALATING"
    else:
        regime = "CALM" if not active_clusters else "MIXED"

    saturation = min(1.0, max(0.0, (flow.post_count - flow.event_cluster_count) / max(flow.post_count, 1)))
    confirmation_rows = [item for item in new_rows if item.update_type in {"CONFIRMATION", "UPDATE"}]
    new_confirmation_quality = (
        sum(item.confidence * item.source_quality for item in confirmation_rows) / len(confirmation_rows)
        if confirmation_rows
        else None
    )
    prior_quality = previous.confirmation_quality if previous else 0.35
    confirmation_quality = prior_quality if new_confirmation_quality is None else (0.6 * prior_quality + 0.4 * new_confirmation_quality)
    supply_risk = max(0.0, values["energy_supply_risk"])
    component = ComponentStatus(
        observed_at=flow.as_of,
        age_seconds=max(0, int((now - datetime.fromisoformat(flow.as_of.replace("Z", "+00:00"))).total_seconds())),
        freshness="FRESH",
        provider="telegram-flow+market-interpretations",
        instrument="selected-markets",
        engine_version=ENGINE_VERSION,
    )
    payload = {
        "as_of": now.isoformat(),
        "previous": previous.snapshot_id if previous else "",
        "new_events": sorted(item.event_id for item in new_rows),
        "state_values": values,
    }
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
        state_values={name: round(values[name], 6) for name in STATE_NAMES},
        state_change={name: round(state_change[name], 6) for name in STATE_NAMES},
        processed_event_ids=tuple(sorted(processed)),
        active_cluster_ids=tuple(sorted(active_clusters)),
    )


def build_decision_states(
    flow: TelegramFlowAssessment,
    information: InformationStateSnapshot,
    *,
    previous: Mapping[str, DecisionStateSnapshot | None] | None = None,
    market_states: Mapping[str, MarketStateSnapshot] | None = None,
) -> list[DecisionStateSnapshot]:
    prior = previous or {}
    technical = market_states or {}
    results: list[DecisionStateSnapshot] = []
    for item in flow.assets:
        old = prior.get(item.asset)
        consensus = float(item.normalized_score)
        impulse_score = market_impulse_score(item.asset, item.flow_score)
        weights = ASSET_WEIGHTS.get(item.asset)
        if weights and information.state_values:
            state_score = max(-1.0, min(1.0, sum(weights[name] * information.state_values.get(name, 0.0) for name in STATE_NAMES)))
            score = 0.65 * state_score + 0.35 * impulse_score
        else:
            state_score = impulse_score
            score = impulse_score
        information_score = max(-1.0, min(1.0, score))
        market_state = technical.get(item.asset)
        technical_score = market_state.direction_score if market_state is not None else 0.0
        if market_state is not None and market_state.component.freshness == "FRESH":
            score = 0.72 * information_score + 0.28 * technical_score
            agreement = information_score * technical_score
            confidence_adjustment = 0.12 if agreement > 0.08 else -0.12 if agreement < -0.08 else 0.0
        else:
            score = information_score
            confidence_adjustment = 0.0
        score = max(-1.0, min(1.0, score))
        confidence = max(0.0, min(1.0, 0.65 * float(item.confidence) + 0.35 * information.confirmation_quality + confidence_adjustment))
        direction = "LONG_BIAS" if score > 0.10 else "SHORT_BIAS" if score < -0.10 else "NEUTRAL"
        if information.component.freshness != "FRESH":
            direction = "STALE"
        elif item.selected_event_count == 0:
            direction = "INSUFFICIENT_DATA"
        change = score - (old.direction_score if old is not None else 0.0)
        payload = {
            "market": item.asset,
            "as_of": flow.as_of,
            "flow_score": item.flow_score,
            "impulse_score": impulse_score,
            "state_score": state_score,
            "information_snapshot_id": information.snapshot_id,
            "market_snapshot_id": market_state.snapshot_id if market_state is not None else "market-confirmation-pending",
        }
        results.append(
            DecisionStateSnapshot(
                snapshot_id=_stable_id("decision-state", payload),
                market=item.asset,
                as_of=flow.as_of,
                previous_snapshot_id=old.snapshot_id if old is not None else "",
                direction=direction,
                direction_score=round(score, 4),
                confidence=confidence,
                expected_move_low_pct=None,
                expected_move_high_pct=None,
                horizon_hours=4.0,
                information_snapshot_id=information.snapshot_id,
                market_snapshot_id=market_state.snapshot_id if market_state is not None else "market-confirmation-pending",
                change_from_previous=round(change, 4),
                contributing_event_ids=tuple(
                    contribution.message_id
                    for contribution in flow.contributions
                    if contribution.asset == item.asset and contribution.selected
                ),
                status_reason=(
                    f"Persistent Information State {state_score:+.2f}; latest flow impulse {impulse_score:+.2f}; "
                    f"directional consensus {consensus:+.2f}. "
                    + (
                        f"Technical confirmation {technical_score:+.2f} from {market_state.component.provider}."
                        if market_state is not None
                        else "Price and technical confirmation pending."
                    )
                ),
                engine_version=ENGINE_VERSION,
            )
        )
    return results


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
