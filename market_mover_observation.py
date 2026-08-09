from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from market_history_store import MarketHistoryStore


@dataclass(frozen=True, slots=True)
class MarketMoverObservation:
    move_pct: float
    elapsed_minutes: int
    start_price: float
    peak_price: float
    start_at: str
    peak_at: str
    observation_complete: bool


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def observe_market_mover(alert, history_store: MarketHistoryStore, *, now: datetime | None = None) -> MarketMoverObservation | None:
    """Measure the strongest realized move within a market-mover horizon.

    The baseline is the first persisted worker price at/after the alert. For an
    UP alert, the strongest positive excursion is selected; for DOWN, the
    strongest negative excursion; for UNCERTAIN, the largest absolute move.
    Timing is therefore the time from the first observed price to the selected
    peak/trough, not simply the age of the alert. The observation window is
    capped at the alert's forecast horizon.
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
    start_at = _utc(start_at_raw)
    start_price = float(start_price_raw)
    if start_price == 0.0:
        return None

    candidates: list[tuple[float, datetime, float]] = []
    for stamp_raw, price_raw in points[1:]:
        stamp = _utc(stamp_raw)
        price = float(price_raw)
        if stamp <= start_at:
            continue
        move_pct = ((price / start_price) - 1.0) * 100.0
        candidates.append((move_pct, stamp, price))
    if not candidates:
        return None

    direction = str(getattr(alert, "expected_direction", "UNCERTAIN")).upper()
    if direction == "UP":
        selected = max(candidates, key=lambda item: item[0])
    elif direction == "DOWN":
        selected = min(candidates, key=lambda item: item[0])
    else:
        selected = max(candidates, key=lambda item: abs(item[0]))

    move_pct, peak_at, peak_price = selected
    elapsed_minutes = max(1, int(round((peak_at - start_at).total_seconds() / 60.0)))
    return MarketMoverObservation(
        move_pct=move_pct,
        elapsed_minutes=elapsed_minutes,
        start_price=start_price,
        peak_price=peak_price,
        start_at=start_at.isoformat(),
        peak_at=peak_at.isoformat(),
        observation_complete=current >= horizon_end,
    )
