from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from db_workspace_persistence_v2 import (
    persist_analysis_recipe,
    persist_baseline_forecast,
    persist_technical_recipe,
    persist_technical_state,
)
from forecast_path_model_v2 import build_forecast_path_v2
from market_history_store import MarketHistoryStore
from technical_core_v2 import (
    TECHNICAL_CORE_V2_RECIPE,
    TechnicalBaselineForecast,
    TechnicalCoreState,
    build_baseline_forecast,
    build_technical_core_state,
)
from timeframe_contract_v2 import build_runtime_frames_from_canonical_1m_v2


DEFAULT_HORIZONS = (300, 900, 1800, 3600, 14400)


@dataclass(frozen=True, slots=True)
class ProducedTechnicalRuntimeV2:
    market: str
    as_of: str
    technical_state: TechnicalCoreState
    baselines: dict[int, TechnicalBaselineForecast]


def _to_utc(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def build_runtime_frames_v2(
    points: Iterable[tuple[str, float]],
    *,
    timeframes: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Compatibility entrypoint backed by the canonical v2 timeframe contract."""
    return build_runtime_frames_from_canonical_1m_v2(points, timeframes=timeframes)


def produce_technical_runtime_v2(
    *,
    market: str,
    history_store: MarketHistoryStore,
    as_of: str | None = None,
    lookback_hours: float = 240.0,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    recipe_version: str = TECHNICAL_CORE_V2_RECIPE,
) -> ProducedTechnicalRuntimeV2:
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be positive")

    end = _to_utc(as_of) if as_of else pd.Timestamp(datetime.now(timezone.utc))
    start = end - pd.Timedelta(hours=float(lookback_hours))
    points = history_store.load_range(
        market=market,
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        limit=max(5000, int(lookback_hours * 120)),
    )
    frames = build_runtime_frames_v2(points)
    state = build_technical_core_state(frames, market=market, recipe_version=recipe_version)
    baselines = {
        int(horizon): build_baseline_forecast(state, horizon_seconds=int(horizon))
        for horizon in horizons
    }
    return ProducedTechnicalRuntimeV2(
        market=market,
        as_of=state.as_of,
        technical_state=state,
        baselines=baselines,
    )


def _frozen_path_spec(produced: ProducedTechnicalRuntimeV2, baseline: TechnicalBaselineForecast) -> dict[str, object]:
    """Capture exactly the phase path that the UI can render for this T0 forecast."""
    path = build_forecast_path_v2(
        state=produced.technical_state,
        horizon_seconds=int(baseline.horizon_seconds),
        direction=baseline.direction,
        expected_return=float(baseline.expected_return),
        lower_return=float(baseline.lower_return),
        upper_return=float(baseline.upper_return),
        path_shape=baseline.path_shape,
    )
    return {
        "path_profile": [[float(x), float(value)] for x, value in path.points],
        "path_rationale": path.rationale,
        "path_phases": list(path.phases),
        "path_source_timeframe": path.source_timeframe,
        "expected_low_return": path.expected_low_return,
        "expected_high_return": path.expected_high_return,
        "path_snapshot_version": "forecast-path-v2",
        "frozen_at_generation": True,
    }


def persist_produced_runtime_v2(
    produced: ProducedTechnicalRuntimeV2,
    *,
    market_id: int,
    technical_recipe_id,
    analysis_recipe_id,
    analysis_recipe_name: str = "technical-only",
    analysis_recipe_version: int = 1,
) -> None:
    persist_technical_recipe(
        technical_recipe_id=technical_recipe_id,
        name=produced.technical_state.recipe_version,
        version=1,
        parameters={"runtime": "canonical-1m-resample-v2.1"},
    )
    technical_state_id = persist_technical_state(
        market_id=market_id,
        technical_recipe_id=technical_recipe_id,
        state=produced.technical_state,
    )
    persist_analysis_recipe(
        analysis_recipe_id=analysis_recipe_id,
        name=analysis_recipe_name,
        version=analysis_recipe_version,
        technical_recipe_id=technical_recipe_id,
        enabled_layers=(),
        layer_versions={},
    )
    for baseline in produced.baselines.values():
        persist_baseline_forecast(
            market_id=market_id,
            technical_state_id=technical_state_id,
            analysis_recipe_id=analysis_recipe_id,
            baseline=baseline,
            frozen_path_spec=_frozen_path_spec(produced, baseline),
        )
