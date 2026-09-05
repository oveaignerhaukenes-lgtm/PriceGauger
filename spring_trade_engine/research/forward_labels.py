from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from spring_trade_engine.contracts import SpringForwardLabelV1
from spring_trade_engine.persistence.evaluation_store import load_pending_forward_label_seeds_v1


DEFAULT_FORWARD_HORIZONS_MINUTES = (5, 15, 30, 60, 120)


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_forward_label_v1(
    *,
    instrument_id: int,
    observed_at: datetime,
    start_price: float,
    horizon_minutes: int,
    future_bars: Sequence[Any],
) -> SpringForwardLabelV1 | None:
    """Label what actually happened after one Spring observation.

    The label is deliberately direction-neutral: terminal return plus the largest
    upward and downward excursions from the observation price. It does not assume a
    LONG/SHORT position and does not decide whether the original state was tradable.
    """
    if start_price <= 0:
        raise ValueError("Spring forward label requires positive start_price")
    horizon = max(1, int(horizon_minutes))
    target_at = _utc(observed_at) + timedelta(minutes=horizon)
    eligible = tuple(item for item in future_bars if _utc(item.bar_time) <= target_at)
    if not eligible:
        return None
    terminal = eligible[-1]
    terminal_at = _utc(terminal.bar_time)
    if terminal_at < target_at - timedelta(minutes=1):
        return None

    highs = [float(item.high) for item in eligible]
    lows = [float(item.low) for item in eligible]
    terminal_close = float(terminal.close)
    return SpringForwardLabelV1(
        instrument_id=int(instrument_id),
        observed_at=_utc(observed_at),
        horizon_minutes=horizon,
        realized_at=terminal_at,
        return_pct=((terminal_close / float(start_price)) - 1.0) * 100.0,
        max_up_excursion_pct=((max(highs) / float(start_price)) - 1.0) * 100.0,
        max_down_excursion_pct=((min(lows) / float(start_price)) - 1.0) * 100.0,
    )


def collect_forward_labels_v1(
    *,
    now: datetime,
    horizons: Sequence[int] = DEFAULT_FORWARD_HORIZONS_MINUTES,
    pending_limit_per_horizon: int = 100,
) -> tuple[SpringForwardLabelV1, ...]:
    store = CanonicalMarketBarStoreV2()
    labels: list[SpringForwardLabelV1] = []
    current = _utc(now)
    for horizon in horizons:
        horizon_minutes = max(1, int(horizon))
        seeds = load_pending_forward_label_seeds_v1(
            horizon_minutes=horizon_minutes,
            eligible_before=current - timedelta(minutes=horizon_minutes),
            limit=pending_limit_per_horizon,
        )
        for seed in seeds:
            future = store.load_instrument_range(
                instrument_id=seed.instrument_id,
                start=_utc(seed.observed_at) + timedelta(minutes=1),
                end=_utc(seed.observed_at) + timedelta(minutes=horizon_minutes + 1),
                limit=horizon_minutes + 2,
            )
            label = build_forward_label_v1(
                instrument_id=seed.instrument_id,
                observed_at=_utc(seed.observed_at),
                start_price=seed.close_price,
                horizon_minutes=horizon_minutes,
                future_bars=future,
            )
            if label is not None:
                labels.append(label)
    return tuple(labels)


__all__ = [
    "DEFAULT_FORWARD_HORIZONS_MINUTES",
    "build_forward_label_v1",
    "collect_forward_labels_v1",
]
