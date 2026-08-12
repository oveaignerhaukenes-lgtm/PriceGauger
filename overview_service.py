from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from adaptation_diagnostics import ForecastAdaptationContext, load_adaptation_contexts
from analysis_status import AnalysisStatusStore, AnalysisStepStatus
from forecast_contracts import DEFAULT_FORECAST_HORIZON_HOURS, ForecastSnapshot
from forecast_error import ForecastErrorObservation, ForecastErrorStore
from forecast_store import ForecastStore
from overview_chart_history import history_days_for_horizon, load_overview_chart_history
from overview_summary_contract import OverviewSummary
from overview_summary_store import OverviewSummaryStore
from state_contracts import DecisionStateSnapshot
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore


RECENT_FORECAST_LIMIT = 200
RECENT_FORECAST_ERROR_LIMIT = 1000


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
    history_days: int = 30
    recommendation_status: str = "PROVISIONAL"
    forecast: ForecastSnapshot | None = None
    forecasts: tuple[ForecastSnapshot, ...] = ()
    forecast_errors: tuple[ForecastErrorObservation, ...] = ()
    adaptation_contexts: Mapping[str, ForecastAdaptationContext] | None = None
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
    db_path: str | Path,
    *,
    market: str,
    forecasts: tuple[ForecastSnapshot, ...],
    horizon_hours: float,
    now: datetime | None = None,
) -> tuple[tuple[str, float], ...]:
    """Load bounded long chart history without rereading months of raw 1m bars."""
    usable = [
        _as_utc(forecast.as_of)
        for forecast in forecasts
        if forecast.horizon_hours is not None
    ]
    usable = [stamp for stamp in usable if stamp is not None]
    if not usable:
        return ()
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return load_overview_chart_history(
        db_path,
        market=market,
        as_of=end.astimezone(timezone.utc),
        horizon_hours=horizon_hours,
    )


def _market(
    item: DecisionStateSnapshot,
    *,
    db_path: str | Path,
    flow: TelegramFlowAssessment | None,
    runtime_store: StateRuntimeStore,
    forecast_store: ForecastStore,
    error_store: ForecastErrorStore,
    horizon_hours: float = DEFAULT_FORECAST_HORIZON_HOURS,
) -> OverviewMarket:
    flow_item = next((asset for asset in (flow.assets if flow is not None else ()) if asset.asset == item.market), None)
    recent = forecast_store.load_all(
        market=item.market,
        horizon_hours=horizon_hours,
        limit=RECENT_FORECAST_LIMIT,
    )
    forecasts = tuple(reversed(recent))
    forecast = forecasts[-1] if forecasts else None
    errors = tuple(
        reversed(
            error_store.load_all(
                market=item.market,
                horizon_hours=horizon_hours,
                limit=RECENT_FORECAST_ERROR_LIMIT,
            )
        )
    )
    adaptation_contexts = load_adaptation_contexts(db_path, errors)
    market_state = runtime_store.load_latest_market_state(market=item.market)
    history = _forecast_timeline_prices(
        db_path,
        market=item.market,
        forecasts=forecasts,
        horizon_hours=horizon_hours,
    )

    if forecast is not None:
        move_low = forecast.expected_move_low_pct
        move_high = forecast.expected_move_high_pct
        horizon = forecast.horizon_hours
    else:
        move_low = item.expected_move_low_pct
        move_high = item.expected_move_high_pct
        horizon = horizon_hours
    history_days = history_days_for_horizon(float(horizon or horizon_hours))
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
        history_days=history_days,
        recommendation_status=_recommendation_status(item),
        forecast=forecast,
        forecasts=forecasts,
        forecast_errors=errors,
        adaptation_contexts=adaptation_contexts,
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
    error_store: ForecastErrorStore,
    horizons_by_market: Mapping[str, float] | None = None,
) -> tuple[OverviewMarket, ...]:
    decisions = runtime_store.load_latest_decision_states()
    selections = horizons_by_market or {}
    return tuple(
        _market(
            item,
            db_path=db_path,
            flow=flow,
            runtime_store=runtime_store,
            forecast_store=forecast_store,
            error_store=error_store,
            horizon_hours=float(selections.get(item.market, DEFAULT_FORECAST_HORIZON_HOURS)),
        )
        for item in decisions
    )


def load_overview_markets(
    db_path: str | Path = "pricegauger.db",
    *,
    horizons_by_market: Mapping[str, float] | None = None,
) -> tuple[OverviewMarket, ...]:
    """Read live cards with an optional independently selected horizon per market."""
    flow = TelegramFlowStore(db_path).load_latest_snapshot()
    return _load_markets(
        db_path=db_path,
        flow=flow,
        runtime_store=StateRuntimeStore(db_path),
        forecast_store=ForecastStore(db_path),
        error_store=ForecastErrorStore(db_path),
        horizons_by_market=horizons_by_market,
    )


def load_overview(db_path: str | Path = "pricegauger.db", *, post_limit: int = 6) -> OverviewData:
    flow_store = TelegramFlowStore(db_path)
    runtime_store = StateRuntimeStore(db_path)
    forecast_store = ForecastStore(db_path)
    error_store = ForecastErrorStore(db_path)
    flow = flow_store.load_latest_snapshot()
    posts = tuple(reversed(flow_store.load_posts(limit=post_limit)))
    markets = _load_markets(
        db_path=db_path,
        flow=flow,
        runtime_store=runtime_store,
        forecast_store=forecast_store,
        error_store=error_store,
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
