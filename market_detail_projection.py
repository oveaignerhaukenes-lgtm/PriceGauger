from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from decision_engine_components import (
    DecisionEngineComponents,
    DecisionEngineComponentStore,
    projected_direction,
    projected_score,
)
from forecast_contracts import ForecastSnapshot, forecast_from_decision
from state_runtime_store import StateRuntimeStore


@dataclass(frozen=True, slots=True)
class MarketDetailProjection:
    forecast: ForecastSnapshot | None
    components: DecisionEngineComponents | None
    score: float | None
    direction: str
    reason: str


def load_market_detail_projection(
    market: str,
    enabled_engines: tuple[str, ...] | list[str],
    *,
    db_path: str = "pricegauger.db",
) -> MarketDetailProjection:
    runtime = StateRuntimeStore(db_path)
    component_store = DecisionEngineComponentStore(db_path)
    decision = runtime.load_latest_decision_state(market=market)
    components = component_store.load_latest(market=market)
    if decision is None or components is None:
        return MarketDetailProjection(None, components, None, "UNAVAILABLE", "Komponentscore er ikke lagret ennå.")
    if components.decision_snapshot_id != decision.snapshot_id:
        return MarketDetailProjection(None, components, None, "UNAVAILABLE", "Komponentscore og Decision State er fra ulike snapshots.")

    score = projected_score(components, enabled_engines)
    direction = projected_direction(score)
    if score is None:
        return MarketDetailProjection(None, components, None, direction, "Ingen aktive og tilgjengelige analysemotorer.")

    market_state = runtime.load_latest_market_state(market=market)
    identity = "|".join([decision.snapshot_id, *sorted(str(item) for item in enabled_engines)])
    projected = replace(
        decision,
        snapshot_id="display-decision:" + sha256(identity.encode("utf-8")).hexdigest()[:24],
        direction=direction,
        direction_score=round(float(score), 4),
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        status_reason="Visningsvariant beregnet fra valgte, lagrede motorkomponenter.",
    )
    forecast = forecast_from_decision(projected, market_state=market_state)
    return MarketDetailProjection(
        forecast=forecast,
        components=components,
        score=score,
        direction=direction,
        reason="Visningsvariant; autoritativt forecast-snapshot er ikke endret.",
    )
