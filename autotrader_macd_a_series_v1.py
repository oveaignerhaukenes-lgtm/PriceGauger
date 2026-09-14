from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from autotrader_hybrid_replay_v1 import replay_hybrid_models_v1
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2


MACD_A_STRATEGY_KEY_V1 = "macd-a-v1"
MACD_A_SERIES_VERSION_V1 = "MACD-A-ADAPTIVE-1-2-5M-v1"


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state(value: float) -> str:
    if float(value) > 0:
        return STATE_LONG
    if float(value) < 0:
        return STATE_SHORT
    return STATE_FLAT


def load_macd_a_series_v1(*, instrument_id: int, seed_equity: float, currency: str, started_at: datetime, as_of: datetime, db_path: str = "pricegauger.db") -> ShadowBenchmarkSeriesV2 | None:
    started, end = _utc(started_at), _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=started - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    if len(bars) < 80:
        return None
    frame, _ = replay_hybrid_models_v1(tuple(bars))
    frame = frame.loc[(frame.index >= started) & (frame.index <= end)]
    if frame.empty:
        return None
    seed = float(seed_equity)
    equity = seed
    state = STATE_FLAT
    prior_price = None
    points: list[ShadowEquityPointV2] = []
    for at, row in frame.iterrows():
        price = float(row["PRICE"])
        if prior_price is not None and prior_price > 0:
            equity = apply_shadow_return_v2(
                equity=equity,
                position_state=state,
                price_return=(price / prior_price) - 1.0,
            )
        state = _state(float(row["TARGET_MACD-A"]))
        stamp = _utc(at.to_pydatetime())
        points.append(ShadowEquityPointV2(closed_at=stamp, equity=float(equity), position_state=state))
        prior_price = price
    return ShadowBenchmarkSeriesV2(
        strategy_key=MACD_A_STRATEGY_KEY_V1,
        execution_mode="SHADOW_ADAPTIVE",
        currency=str(currency),
        seed_equity=seed,
        started_at=points[0].closed_at,
        points=tuple(points),
    )


__all__ = ["MACD_A_SERIES_VERSION_V1", "MACD_A_STRATEGY_KEY_V1", "load_macd_a_series_v1"]
