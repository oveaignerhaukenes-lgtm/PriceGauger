from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis_status import AnalysisStatusStore, AnalysisStepStatus
from forecast_contracts import ForecastSnapshot
from forecast_store import ForecastStore
from market_history_store import MarketHistoryStore
from overview_summary_contract import OverviewSummary
from overview_summary_store import OverviewSummaryStore
from state_contracts import DecisionStateSnapshot
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore


# Retrieval safety bound only. The renderer no longer uses snapshot count as the
# visible-lifetime rule; it keeps every forecast whose horizon overlaps the
# rolling chart viewport.
RECENT_FORECAST_LIMIT = 200


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
    forecast: ForecastSnapshot | None = None
    forecasts: tuple[ForecastSnapshot, ...] = ()
    price_history: tuple[tuple[str, float], ...] = ()
    market_regime: str = ""
    volatility_score: float | None = None


@dataclass(frozen=True, slots=True)
class OverviewData:
    flow: TelegramFlowAssessment | None
    markets: tuple[OverviewMarket, ...]
    latest_posts: tuple[ScoredTelegramPost, ...]
    information_state: dict | None
    latest_alert: object | None
    summary: OverviewSummary | None = None
    analysis_steps: tuple[AnalysisStepStatus, ...] = ()


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


def _as_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _forecast_timeline_prices(
    history_store: MarketHistoryStore,
    *,
    market: str,
    forecasts: tuple[ForecastSnapshot, ...],
    now: datetime | None = None,
) -> tuple[tuple[str, float], ...]:
    """Load canonical history for a rolling forecast viewport.

    Keep one *active-market* horizon before the newest forecast so a weekend or
    provider gap still has a real point on both sides for gap classification, then
    read forward from the forecast through all currently persisted observations.
    Forecast lifetime itself remains a renderer concern based on temporal overlap.
    """

    usable: list[tuple[ForecastSnapshot, datetime, datetime]] = []
    for forecast in forecasts:
        as_of = _as_utc(forecast.as_of)
        if as_of is None or forecast.horizon_hours is None:
            continue
        horizon_hours = max(0.25, float(forecast.horizon_hours))
        usable.append((forecast, as_of, as_of + timedelta(hours=horizon_hours)))
    if not usable:
        return ()

    usable.sort(key=lambda item: item[1])
    latest, latest_as_of, _ = usable[-1]
    horizon_hours = max(0.25, float(latest.horizon_hours or 0.25))
    before = history_store.load_window(
        market=market,
        as_of=latest_as_of.isoformat(),
        horizon_hours=horizon_hours,
        limit=4000,
    )
    after = history_store.load_since(
        market=market,
        start=latest_as_of,
        limit=10000,
    )
    merged: dict[str, float] = {}
    for stamp, price in (*before, *after):
        merged[str(stamp)] = float(price)
    return tuple(sorted(merged.items(), key=lambda item: item[0]))


def _market(
    item: DecisionStateSnapshot,
    *,
    flow: TelegramFlowAssessment | None,
    runtime_store: StateRuntimeStore,
    forecast_store: ForecastStore,
    history_store: MarketHistoryStore,
) -> OverviewMarket:
    flow_item = next((asset for asset in (flow.assets if flow is not None else ()) if asset.asset == item.market), None)
    recent = forecast_store.load_all(market=item.market, limit=RECENT_FORECAST_LIMIT)
    forecasts = tuple(reversed(recent))
    forecast = forecasts[-1] if forecasts else None
    market_state = runtime_store.load_latest_market_state(market=item.market)
    history = _forecast_timeline_prices(
        history_store,
        market=item.market,
        forecasts=forecasts,
    )

    move_low = item.expected_move_low_pct
    move_high = item.expected_move_high_pct
    horizon = item.horizon_hours
    if forecast is not None:
        if move_low is None:
            move_low = forecast.expected_move_low_pct
        if move_high is None:
            move_high = forecast.expected_move_high_pct
        if horizon is None:
            horizon = forecast.horizon_hours
    return OverviewMarket(
        market=item.market,
        direction=item.direction,
        score=float(item.direction_score),
        confidence=float(item.confidence),
        event_count=int(flow_item.selected_event_count) if flow_item is not None else len(item.contributing_event_ids),
        top_driver=(flow_item.top_drivers[0] if flow_item is not None and flow_item.top_drivers else "Ingen tydelig hoveddriver."),
        change_from_previous=float(item.change_from_previous),
        status_reason=item.status_reason,
        expected_move_low_pct=move_low,
        expected_move_high_pct=move_high,
        horizon_hours=horizon,
        recommendation_status=_recommendation_status(item),
        forecast=forecast,
        forecasts=forecasts,
        price_history=history,
        market_regime="" if market_state is None else market_state.regime,
        volatility_score=None if market_state is None else market_state.volatility_score,
    )


def _load_markets(
    *,
    db_path: str | Path,
    flow: TelegramFlowAssessment | None,
    runtime_store: StateRuntimeStore,
    forecast_store: ForecastStore,
    history_store: MarketHistoryStore,
) -> tuple[OverviewMarket, ...]:
    decisions = runtime_store.load_latest_decision_states()
    return tuple(
        _market(
            item,
            flow=flow,
            runtime_store=runtime_store,
            forecast_store=forecast_store,
            history_store=history_store,
        )
        for item in decisions
    )


def load_overview_markets(db_path: str | Path = "pricegauger.db") -> tuple[OverviewMarket, ...]:
    """Read only the live market-card state; safe to call from a UI refresh fragment."""
    flow = TelegramFlowStore(db_path).load_latest_snapshot()
    return _load_markets(
        db_path=db_path,
        flow=flow,
        runtime_store=StateRuntimeStore(db_path),
        forecast_store=ForecastStore(db_path),
        history_store=MarketHistoryStore(db_path),
    )


def load_overview(db_path: str | Path = "pricegauger.db", *, post_limit: int = 6) -> OverviewData:
    flow_store = TelegramFlowStore(db_path)
    runtime_store = StateRuntimeStore(db_path)
    forecast_store = ForecastStore(db_path)
    history_store = MarketHistoryStore(db_path)
    flow = flow_store.load_latest_snapshot()
    posts = tuple(reversed(flow_store.load_posts(limit=post_limit)))
    markets = _load_markets(
        db_path=db_path,
        flow=flow,
        runtime_store=runtime_store,
        forecast_store=forecast_store,
        history_store=history_store,
    )
    return OverviewData(
        flow=flow,
        markets=markets,
        latest_posts=posts,
        information_state=runtime_store.load_latest_information_state(),
        latest_alert=runtime_store.load_latest_alert(),
        summary=OverviewSummaryStore(db_path).load_latest(),
        analysis_steps=AnalysisStatusStore(db_path).load(),
    )
