"""Costed closed-bar shadow curve for Aen#1; execution remains disabled."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

from autotrader_aen1_v1 import Aen1, Aen1Config, SERIES_VERSION, STRATEGY_KEY
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS, BENCHMARK_WARMUP_DAYS,
    ShadowBenchmarkSeriesV2, ShadowEquityPointV2, apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2


def _utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def replay_aen1_series_v1(bars, *, seed_equity: float, currency: str,
                          started_at: datetime, as_of: datetime,
                          config: Aen1Config | None = None) -> ShadowBenchmarkSeriesV2 | None:
    """Compute old-state return, then new-state half-spread at each closed bar.

    Warmup prior to started_at is strictly signal-only. No return is credited
    before the requested benchmark start. Minute OHLC does not reconstruct fills.
    """
    seed = float(seed_equity)
    if not isfinite(seed) or seed <= 0:
        raise ValueError("seed_equity must be positive and finite")
    start, end = _utc(started_at), _utc(as_of)
    policy = Aen1(config or Aen1Config())
    equity = seed
    previous_price = None
    previous_state = "FLAT"
    previous_at = None
    points = []
    for bar in sorted(bars, key=lambda item: _utc(item.bar_time)):
        at = _utc(bar.bar_time) + timedelta(minutes=1)
        if at > end:
            break
        price = float(bar.close)
        if not isfinite(price) or price <= 0:
            continue
        if previous_at is not None and at <= previous_at:
            continue
        if at <= start:
            policy.on_close(at, price)
            previous_price, previous_at = price, at
            continue
        # Restart research equity flat at the common start, independent of
        # whether pre-start warmup would have entered a position.
        if not points:
            policy.state = "FLAT"
            policy.entry_price = policy.best_price = None
            policy.last_exit_at = None
        if previous_price is not None and points:
            equity = apply_shadow_return_v2(
                equity=equity, position_state=previous_state,
                price_return=price / previous_price - 1.0,
            )
        policy.on_close(at, price)
        target = policy.state
        units = {"SHORT": -1, "FLAT": 0, "LONG": 1}
        legs = abs(units[target] - units[previous_state])
        if legs:
            equity *= max(0.0, 1.0 - (legs * policy.config.assumed_spread_points / (2.0 * price)))
        points.append(ShadowEquityPointV2(at, equity, target))
        previous_price, previous_at, previous_state = price, at, target
    if not points:
        return None
    return ShadowBenchmarkSeriesV2(
        strategy_key=STRATEGY_KEY, execution_mode="SHADOW_COSTED",
        currency=str(currency), seed_equity=seed,
        started_at=points[0].closed_at, points=tuple(points),
    )


def load_aen1_series_v1(*, instrument_id: int, seed_equity: float, currency: str,
                        started_at: datetime, as_of: datetime,
                        db_path: str = "pricegauger.db") -> ShadowBenchmarkSeriesV2 | None:
    start, end = _utc(started_at), _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id), start=start - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end, limit=BENCHMARK_MAX_1M_BARS,
    )
    if not bars:
        return None
    return replay_aen1_series_v1(bars, seed_equity=seed_equity, currency=currency,
                                 started_at=start, as_of=end)


__all__ = ["SERIES_VERSION", "replay_aen1_series_v1", "load_aen1_series_v1"]
