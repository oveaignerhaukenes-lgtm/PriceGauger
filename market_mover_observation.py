from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from market_history_store import MarketHistoryStore


@dataclass(frozen=True, slots=True)
class MarketMoverObservation:
    move_pct: float
    elapsed_minutes: int
    start_price: float
    end_price: float
    start_at: str
    end_at: str


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def observe_market_mover(alert, history_store: MarketHistoryStore, *, now: datetime | None = None) -> MarketMoverObservation | None:
    """Measure realized price movement after a market-mover alert.

    Uses persisted worker observations only. The observation window starts at the
    alert timestamp and is capped at the alert's forecast horizon. At least two
    observed market prices are required so the UI never presents an invented
    realized move.
    """
    created_at = _utc(str(alert.created_at))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horizon_end = created_at + timedelta(hours=max(0.0, float(alert.horizon_hours)))
    end = min(current, horizon_end)
    if end <= created_at:
        return None

    points = history_store.load_range(
        market=str(alert.market),
        start=created_at,
        end=end,
        limit=10000,
    )
    if len(points) < 2:
        return None

    start_at_raw, start_price_raw = points[0]
    end_at_raw, end_price_raw = points[-1]
    start_at = _utc(start_at_raw)
    end_at = _utc(end_at_raw)
    start_price = float(start_price_raw)
    end_price = float(end_price_raw)
    if start_price == 0.0 or end_at <= start_at:
        return None

    move_pct = ((end_price / start_price) - 1.0) * 100.0
    elapsed_minutes = max(1, int(round((end_at - start_at).total_seconds() / 60.0)))
    return MarketMoverObservation(
        move_pct=move_pct,
        elapsed_minutes=elapsed_minutes,
        start_price=start_price,
        end_price=end_price,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
    )
