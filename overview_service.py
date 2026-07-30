from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import AssetFlowAssessment, ScoredTelegramPost, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore


@dataclass(frozen=True, slots=True)
class OverviewMarket:
    market: str
    direction: str
    score: float
    confidence: float
    event_count: int
    top_driver: str


@dataclass(frozen=True, slots=True)
class OverviewData:
    flow: TelegramFlowAssessment | None
    markets: tuple[OverviewMarket, ...]
    latest_posts: tuple[ScoredTelegramPost, ...]
    information_state: dict | None
    latest_alert: object | None


def _market(item: AssetFlowAssessment) -> OverviewMarket:
    return OverviewMarket(
        market=item.asset,
        direction=item.direction,
        score=float(item.normalized_score),
        confidence=float(item.confidence),
        event_count=int(item.selected_event_count),
        top_driver=item.top_drivers[0] if item.top_drivers else "Ingen tydelig hoveddriver.",
    )


def load_overview(db_path: str | Path = "pricegauger.db", *, post_limit: int = 6) -> OverviewData:
    flow_store = TelegramFlowStore(db_path)
    runtime_store = StateRuntimeStore(db_path)
    flow = flow_store.load_latest_snapshot()
    posts = tuple(reversed(flow_store.load_posts(limit=post_limit)))
    markets = tuple(_market(item) for item in flow.assets) if flow is not None else ()
    return OverviewData(
        flow=flow,
        markets=markets,
        latest_posts=posts,
        information_state=runtime_store.load_latest_information_state(),
        latest_alert=runtime_store.load_latest_alert(),
    )
