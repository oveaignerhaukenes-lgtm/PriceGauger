from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from asset_state_mapping import ASSET_WEIGHTS, AssetRecommendation, build_asset_recommendation
from event_resolution import CanonicalEvent
from market_interpretation import MarketInterpretation
from market_interpreter import MockMarketInterpreter
from market_state import MarketState, build_market_state
from market_state_store import MarketStateStore


@dataclass(frozen=True, slots=True)
class MarketStateResult:
    interpretation: MarketInterpretation
    state: MarketState
    recommendations: tuple[AssetRecommendation, ...]
    created: bool


def process_market_event(
    event: CanonicalEvent,
    *,
    interpreter=None,
    store: MarketStateStore | None = None,
    update_type: str = "NEW_EVENT",
    as_of: datetime | None = None,
) -> MarketStateResult:
    interpreter = interpreter or MockMarketInterpreter()
    store = store or MarketStateStore()
    existing = {item.event_id: item for item in store.load_interpretations()}
    created = event.event_id not in existing
    interpretation = existing.get(event.event_id)
    if interpretation is None:
        interpretation = interpreter.interpret(event, update_type=update_type)
        store.save_interpretation(interpretation)

    now = as_of or datetime.now(timezone.utc)
    interpretations = store.load_interpretations()
    state = build_market_state(interpretations, as_of=now)
    recommendations = tuple(build_asset_recommendation(asset, state) for asset in ASSET_WEIGHTS)
    store.save_snapshot(state, recommendations)
    return MarketStateResult(interpretation, state, recommendations, created)
