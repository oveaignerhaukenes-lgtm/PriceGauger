from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Any

from autotrader_ai_baseline_v1 import (
    MAX_DECISION_AGE,
    STRATEGY_KEY,
    ensure_ai_baseline_schema_v1,
)
from autotrader_shadow_benchmark_v2 import (
    STATE_FLAT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect


FRESH_SERIES_VERSION_V1 = "AI-BASELINE-FRESHNESS-CAPPED-v1"


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _price_lookup_v1(*, instrument_id: int, start: datetime, end: datetime, db_path: str) -> tuple[list[datetime], list[float]]:
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=start - timedelta(minutes=2),
        end=end,
        limit=50_000,
    )
    clocks: list[datetime] = []
    prices: list[float] = []
    for bar in bars:
        closed_at = _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)
        clocks.append(closed_at)
        prices.append(float(bar.close))
    return clocks, prices


def _price_at_or_before_v1(clocks: list[datetime], prices: list[float], at: datetime, fallback: float) -> float:
    if not clocks:
        return float(fallback)
    index = bisect_right(clocks, _utc(at)) - 1
    if index < 0:
        return float(fallback)
    return float(prices[index])


def load_ai_baseline_fresh_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str = "pricegauger.db",
) -> ShadowBenchmarkSeriesV2 | None:
    """Reconstruct AI baseline without granting stale decisions indefinite exposure.

    A decision remains active only while it is fresh. If no replacement decision
    arrives before ``MAX_DECISION_AGE``, the simulated model goes FLAT at expiry and
    stays FLAT until a later real decision arrives. This keeps disabled/failed models
    from earning artificial credit from one old LONG/SHORT call.
    """
    ensure_ai_baseline_schema_v1()
    start = _utc(started_at)
    end = _utc(as_of)
    with connect() as db:
        rows = db.execute(
            """
            SELECT action_at, price, target_direction
            FROM pg_v2_autotrader_ai_baseline_samples
            WHERE strategy_key = ? AND instrument_id = ?
              AND action_at >= ? AND action_at <= ?
            ORDER BY action_at ASC
            """,
            (STRATEGY_KEY, int(instrument_id), start, end),
        ).fetchall()
    if not rows:
        return None

    decisions: list[tuple[datetime, float, str]] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0], "price": row[1], "target_direction": row[2]
        }
        decisions.append((_utc(values["action_at"]), float(values["price"]), str(values["target_direction"])))

    first_at, first_price, state = decisions[0]
    clocks, prices = _price_lookup_v1(
        instrument_id=int(instrument_id),
        start=first_at,
        end=end,
        db_path=db_path,
    )
    equity = float(seed_equity)
    previous_at = first_at
    previous_price = float(first_price)
    points: list[ShadowEquityPointV2] = [
        ShadowEquityPointV2(closed_at=first_at, equity=equity, position_state=state)
    ]

    for action_at, decision_price, next_state in decisions[1:]:
        expiry = min(previous_at + MAX_DECISION_AGE, action_at)
        if expiry < action_at:
            expiry_price = _price_at_or_before_v1(clocks, prices, expiry, previous_price)
            if previous_price > 0:
                equity = apply_shadow_return_v2(
                    equity=equity,
                    position_state=state,
                    price_return=(expiry_price / previous_price) - 1.0,
                )
            state = STATE_FLAT
            points.append(ShadowEquityPointV2(closed_at=expiry, equity=float(equity), position_state=STATE_FLAT))
            previous_price = expiry_price
        else:
            if previous_price > 0:
                equity = apply_shadow_return_v2(
                    equity=equity,
                    position_state=state,
                    price_return=(float(decision_price) / previous_price) - 1.0,
                )

        state = next_state
        previous_at = action_at
        previous_price = float(decision_price)
        points.append(ShadowEquityPointV2(closed_at=action_at, equity=float(equity), position_state=state))

    expiry = previous_at + MAX_DECISION_AGE
    if end > previous_at:
        active_until = min(end, expiry)
        active_price = _price_at_or_before_v1(clocks, prices, active_until, previous_price)
        if previous_price > 0:
            equity = apply_shadow_return_v2(
                equity=equity,
                position_state=state,
                price_return=(active_price / previous_price) - 1.0,
            )
        if active_until > previous_at:
            final_state = state if end <= expiry else STATE_FLAT
            points.append(
                ShadowEquityPointV2(
                    closed_at=active_until,
                    equity=float(equity),
                    position_state=final_state,
                )
            )
        if end > expiry:
            points.append(ShadowEquityPointV2(closed_at=end, equity=float(equity), position_state=STATE_FLAT))

    return ShadowBenchmarkSeriesV2(
        strategy_key=STRATEGY_KEY,
        execution_mode="SHADOW_ADAPTIVE",
        currency=str(currency),
        seed_equity=float(seed_equity),
        started_at=first_at,
        points=tuple(points),
    )


__all__ = ["FRESH_SERIES_VERSION_V1", "load_ai_baseline_fresh_series_v1"]
