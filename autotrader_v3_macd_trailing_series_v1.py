from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS, BENCHMARK_WARMUP_DAYS,
    ShadowBenchmarkSeriesV2, ShadowEquityPointV2,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import (
    STRATEGY_KEY_V3, MacdTrailingConfigV3, macd_trailing_target_v3,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2

SERIES_VERSION_V3 = "MACD-TRAILING-5M-v1"
DEFAULT_TIMEFRAME_MINUTES_V3 = 5


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_macd_trailing_shadow_series_v3(
    *, instrument_id: int, seed_equity: float, currency: str,
    started_at: datetime, as_of: datetime, db_path: str = "pricegauger.db",
    timeframe_minutes: int = DEFAULT_TIMEFRAME_MINUTES_V3,
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> ShadowBenchmarkSeriesV2 | None:
    """Replay inventory-native MACD-Trailing on canonical 1m prices, read-only."""
    seed = float(seed_equity)
    if not math.isfinite(seed) or seed <= 0:
        raise ValueError("seed_equity must be finite and positive")
    started, end = _utc(started_at), _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id), start=started - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end, limit=BENCHMARK_MAX_1M_BARS,
    )
    if not bars:
        return None
    minutes = int(timeframe_minutes)
    closed = closed_bars_v2(tuple(item.point for item in bars), market=str(bars[0].market_name), timeframe_minutes=minutes)
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    by_action = {_utc(item.closed_at): item for item in observations}

    price_clock = tuple(item for item in bars if started <= _utc(item.bar_time) + timedelta(minutes=1) <= end)
    if not price_clock:
        return None
    equity, target = seed, TargetInventoryV3(0.0)
    previous_obs = None
    prior_price = float(price_clock[0].close)
    first_at = _utc(price_clock[0].bar_time) + timedelta(minutes=1)
    points = [ShadowEquityPointV2(first_at, equity, "FLAT")]

    for bar in price_clock[1:]:
        at = _utc(bar.bar_time) + timedelta(minutes=1)
        price = float(bar.close)
        if price <= 0 or prior_price <= 0:
            raise ValueError("MACD-Trailing shadow price must be positive")
        exposure = target.amount / config.max_inventory
        equity = max(0.0, equity * (1.0 + exposure * ((price / prior_price) - 1.0)))
        observation = by_action.get(at)
        if equity <= 0:
            target = TargetInventoryV3(0.0)
        elif observation is not None:
            decision = macd_trailing_target_v3(
                current_target=target, observation=observation,
                previous_observation=previous_obs, config=config,
            )
            target = decision.target
            previous_obs = observation
        state = "LONG" if target.amount > 0 else "SHORT" if target.amount < 0 else "FLAT"
        points.append(ShadowEquityPointV2(at, equity, state))
        prior_price = price

    return ShadowBenchmarkSeriesV2(
        strategy_key=STRATEGY_KEY_V3, execution_mode="V3_SHADOW",
        currency=str(currency), seed_equity=seed, started_at=first_at, points=tuple(points),
    )


__all__ = ["SERIES_VERSION_V3", "DEFAULT_TIMEFRAME_MINUTES_V3", "load_macd_trailing_shadow_series_v3"]
