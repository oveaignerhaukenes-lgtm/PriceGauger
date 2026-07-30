from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from state_contracts import DecisionStateSnapshot
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore


@dataclass(frozen=True, slots=True)
class OverviewMarket:
    market: str
    direction: str
    score: float
    confidence: float
    event_count: int
    top_driver: str
    change_from_previous: float
    status_reason: str


@dataclass(frozen=True, slots=True)
class OverviewData:
    flow: TelegramFlowAssessment | None
    markets: tuple[OverviewMarket, ...]
    latest_posts: tuple[ScoredTelegramPost, ...]
    information_state: dict | None
    latest_alert: object | None


def _market(
    item: DecisionStateSnapshot,
    *,
    flow: TelegramFlowAssessment | None,
) -> OverviewMarket:
    flow_item = next((asset for asset in (flow.assets if flow is not None else ()) if asset.asset == item.market), None)
    return OverviewMarket(
        market=item.market,
        direction=item.direction,
        score=float(item.direction_score),
        confidence=float(item.confidence),
        event_count=int(flow_item.selected_event_count) if flow_item is not None else len(item.contributing_event_ids),
        top_driver=(flow_item.top_drivers[0] if flow_item is not None and flow_item.top_drivers else "Ingen tydelig hoveddriver."),
        change_from_previous=float(item.change_from_previous),
        status_reason=item.status_reason,
    )


def load_overview(db_path: str | Path = "pricegauger.db", *, post_limit: int = 6) -> OverviewData:
    flow_store = TelegramFlowStore(db_path)
    runtime_store = StateRuntimeStore(db_path)
    flow = flow_store.load_latest_snapshot()
    posts = tuple(reversed(flow_store.load_posts(limit=post_limit)))
    decisions = runtime_store.load_latest_decision_states()
    markets = tuple(_market(item, flow=flow) for item in decisions)
    return OverviewData(
        flow=flow,
        markets=markets,
        latest_posts=posts,
        information_state=runtime_store.load_latest_information_state(),
        latest_alert=runtime_store.load_latest_alert(),
    )
