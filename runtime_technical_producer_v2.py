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
from market_history_store import MarketHistoryStore
from technical_core_v2 import (
    TECHNICAL_CORE_V2_RECIPE,
    TechnicalBaselineForecast,
    TechnicalCoreState,
    build_baseline_forecast,
    build_technical_core_state,
)


DEFAULT_TIMEFRAMES: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
}
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


def _one_minute_frame(points: Iterable[tuple[str, float]]) -> pd.DataFrame:
    rows = [(stamp, float(price)) for stamp, price in points]
    if not rows:
        raise ValueError("Technical Core v2 producer requires canonical 1m history")
    frame = pd.DataFrame(rows, columns=["timestamp", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
    frame = frame.drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise ValueError("Canonical 1m history contained no valid observations")
    # Canonical v1 history currently exposes close-only points. Use close as OHLC so
    # trend/momentum remain live without inventing intrabar range or volume.
    for column in ("open", "high", "low"):
        frame[column] = frame["close"]
    return frame.reset_index(drop=True)


def _complete_resampled_bars(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    data = frame.set_index("timestamp")
    aggregated = data.resample(rule, label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    aggregated = aggregated.dropna(subset=["close"])
    if aggregated.empty:
        return aggregated.reset_index()

    latest_observation = frame["timestamp"].iloc[-1]
    complete = aggregated.loc[aggregated.index <= latest_observation]
    return complete.reset_index()


def build_runtime_frames_v2(
    points: Iterable[tuple[str, float]],
    *,
    timeframes: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    one_minute = _one_minute_frame(points)
    frames: dict[str, pd.DataFrame] = {"1m": one_minute}
    for name, rule in (timeframes or DEFAULT_TIMEFRAMES).items():
        frames[name] = _complete_resampled_bars(one_minute, rule)
    return frames


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
        )
