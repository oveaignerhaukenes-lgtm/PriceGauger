from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from overview_summary_contract import OverviewSummary
from overview_summary_store import OverviewSummaryStore
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
    expected_move_low_pct: float | None = None
    expected_move_high_pct: float | None = None
    horizon_hours: float | None = None
    recommendation_status: str = "PROVISIONAL"


@dataclass(frozen=True, slots=True)
class OverviewData:
    flow: TelegramFlowAssessment | None
    markets: tuple[OverviewMarket, ...]
    latest_posts: tuple[ScoredTelegramPost, ...]
    information_state: dict | None
    latest_alert: object | None
    summary: OverviewSummary | None = None


def _recommendation_status(item: DecisionStateSnapshot) -> str:
    has_interval = item.expected_move_low_pct is not None and item.expected_move_high_pct is not None
    has_market_confirmation = bool(item.market_snapshot_id and item.market_snapshot_id != "market-confirmation-pending")
    if (
        item.direction in {"LONG_BIAS", "SHORT_BIAS", "NEUTRAL"}
        and has_interval
        and has_market_confirmation
        and item.confidence >= 0.5
    ):
        return "ACTIONABLE"
    return "PROVISIONAL"


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
        expected_move_low_pct=item.expected_move_low_pct,
        expected_move_high_pct=item.expected_move_high_pct,
        horizon_hours=item.horizon_hours,
        recommendation_status=_recommendation_status(item),
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
        summary=OverviewSummaryStore(db_path).load_latest(),
    )
