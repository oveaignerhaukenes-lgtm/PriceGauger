from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Iterable

import pandas as pd


@dataclass(slots=True)
class TrajectoryPoint:
    minutes_ahead: int
    expected_pct: float
    lower_pct: float
    upper_pct: float

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TradePlan:
    instrument: str
    direction: str
    setup: str
    status: str
    created_at: str
    reference_price: float
    entry_low: float | None
    entry_high: float | None
    activation_price: float | None
    invalidation_price: float | None
    target_1: float | None
    target_2: float | None
    entry_window: str
    target_window: str
    expires_after_minutes: int
    confidence_pct: float
    signal_quality: float
    expected_move_pct: float
    expected_path: list[str]
    trajectory: list[TrajectoryPoint]
    rationale: list[str]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["trajectory"] = [point.to_record() for point in self.trajectory]
        return record


def _latest_price(market: pd.DataFrame) -> float:
    if market.empty or "close" not in market:
        raise ValueError("Market frame has no close prices")
    closes = pd.to_numeric(market["close"], errors="coerce").dropna()
    if closes.empty:
        raise ValueError("Market frame has no valid close prices")
    return float(closes.iloc[-1])


def _realized_volatility_pct(market: pd.DataFrame, lookback: int = 48) -> float:
    if market.empty or "close" not in market:
        return 0.35
    closes = pd.to_numeric(market["close"], errors="coerce").dropna().tail(lookback + 1)
    returns = closes.pct_change().dropna() * 100.0
    if len(returns) < 3:
        return 0.35
    value = float(returns.std(ddof=0))
    return max(0.05, min(4.0, value))


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _price(reference: float, move_pct: float) -> float:
    return reference * (1.0 + move_pct / 100.0)


def _direction_sign(direction: str) -> int:
    return 1 if direction.upper() == "LONG" else -1 if direction.upper() == "SHORT" else 0


def build_trajectory(
    *,
    expected_move_pct: float,
    confidence_pct: float,
    volatility_pct: float,
    horizons_minutes: Iterable[int] = (0, 15, 30, 60, 120, 240),
) -> list[TrajectoryPoint]:
    """Create a widening trajectory cone around a directional expectation.

    The centre path approaches the expected move asymptotically. Uncertainty grows
    with the square root of time and is reduced by signal confidence, but never
    collapses to zero. This is deliberately transparent and deterministic so that
    later calibration can replace the coefficients without changing the interface.
    """
    confidence = _bounded(confidence_pct / 100.0, 0.0, 0.95)
    quality_penalty = 1.15 - 0.75 * confidence
    points: list[TrajectoryPoint] = []
    max_horizon = max(max(horizons_minutes), 1)

    for minutes in horizons_minutes:
        progress = 0.0 if minutes <= 0 else 1.0 - (0.5 ** (minutes / max(max_horizon / 2.0, 1.0)))
        centre = expected_move_pct * progress
        time_scale = sqrt(max(minutes, 1) / 15.0)
        uncertainty = volatility_pct * time_scale * quality_penalty
        points.append(
            TrajectoryPoint(
                minutes_ahead=int(minutes),
                expected_pct=round(centre, 4),
                lower_pct=round(centre - uncertainty, 4),
                upper_pct=round(centre + uncertainty, 4),
            )
        )
    return points


def build_trade_plan(
    *,
    instrument: str,
    market: pd.DataFrame,
    direction: str,
    confidence_pct: float,
    expected_move_pct: float | None,
    rationale: Iterable[str] = (),
    response_role: str = "UNCLASSIFIED",
    expected_response_window: str = "15–60 min",
) -> TradePlan:
    reference = _latest_price(market)
    volatility = _realized_volatility_pct(market)
    sign = _direction_sign(direction)
    expected_abs = abs(float(expected_move_pct or 0.0))

    if sign == 0 or confidence_pct < 45.0 or expected_abs < 0.05:
        trajectory = build_trajectory(
            expected_move_pct=0.0,
            confidence_pct=confidence_pct,
            volatility_pct=volatility,
        )
        return TradePlan(
            instrument=instrument,
            direction="NEUTRAL",
            setup="Avvent målbar aktivering",
            status="NO_TRADE",
            created_at=datetime.now(timezone.utc).isoformat(),
            reference_price=reference,
            entry_low=None,
            entry_high=None,
            activation_price=None,
            invalidation_price=None,
            target_1=None,
            target_2=None,
            entry_window=expected_response_window,
            target_window="—",
            expires_after_minutes=60,
            confidence_pct=confidence_pct,
            signal_quality=round(confidence_pct / 100.0, 3),
            expected_move_pct=0.0,
            expected_path=["Ingen inngang før retning og aktivering er målbar."],
            trajectory=trajectory,
            rationale=list(rationale),
        )

    expected_signed = sign * expected_abs
    pullback_pct = _bounded(volatility * 0.55, 0.08, max(0.12, expected_abs * 0.45))
    entry_width_pct = _bounded(volatility * 0.30, 0.04, 0.30)
    stop_distance_pct = _bounded(max(volatility * 1.20, expected_abs * 0.42), 0.20, 3.0)
    target_1_pct = sign * max(expected_abs * 0.55, volatility * 0.70)
    target_2_pct = sign * max(expected_abs * 0.90, volatility * 1.20)

    if sign > 0:
        entry_centre = _price(reference, -pullback_pct)
        entry_low = _price(entry_centre, -entry_width_pct / 2.0)
        entry_high = _price(entry_centre, entry_width_pct / 2.0)
        activation = entry_high
        invalidation = _price(reference, -stop_distance_pct)
        setup = "LONG på rekyl med bekreftet gjenerobring av inngangssonen"
        path = ["Rekyl", "Stabilisering", "Gjenerobring", "Fortsettelse opp"]
    else:
        entry_centre = _price(reference, pullback_pct)
        entry_low = _price(entry_centre, -entry_width_pct / 2.0)
        entry_high = _price(entry_centre, entry_width_pct / 2.0)
        activation = entry_low
        invalidation = _price(reference, stop_distance_pct)
        setup = "SHORT på rekyl med bekreftet avvisning fra inngangssonen"
        path = ["Rekyl opp", "Avvisning", "Brudd ned", "Fortsettelse ned"]

    trajectory = build_trajectory(
        expected_move_pct=expected_signed,
        confidence_pct=confidence_pct,
        volatility_pct=volatility,
    )
    role_note = f"Responsrolle: {response_role}." if response_role else ""

    return TradePlan(
        instrument=instrument,
        direction=direction.upper(),
        setup=setup,
        status="WAITING_FOR_ENTRY",
        created_at=datetime.now(timezone.utc).isoformat(),
        reference_price=round(reference, 6),
        entry_low=round(entry_low, 6),
        entry_high=round(entry_high, 6),
        activation_price=round(activation, 6),
        invalidation_price=round(invalidation, 6),
        target_1=round(_price(reference, target_1_pct), 6),
        target_2=round(_price(reference, target_2_pct), 6),
        entry_window=expected_response_window,
        target_window="1–4 timer",
        expires_after_minutes=60,
        confidence_pct=round(confidence_pct, 1),
        signal_quality=round(confidence_pct / 100.0, 3),
        expected_move_pct=round(expected_signed, 4),
        expected_path=path,
        trajectory=trajectory,
        rationale=[role_note, *list(rationale)] if role_note else list(rationale),
    )


def update_plan_status(plan: TradePlan, current_price: float) -> str:
    """Evaluate the current lifecycle state without rewriting the original plan."""
    if plan.status == "NO_TRADE" or plan.entry_low is None or plan.entry_high is None:
        return "NO_TRADE"

    if plan.direction == "LONG":
        if plan.invalidation_price is not None and current_price <= plan.invalidation_price:
            return "INVALIDATED"
        if plan.target_2 is not None and current_price >= plan.target_2:
            return "TARGET_2_HIT"
        if plan.target_1 is not None and current_price >= plan.target_1:
            return "TARGET_1_HIT"
        if plan.entry_low <= current_price <= plan.entry_high:
            return "ENTRY_ZONE"
        if current_price > plan.entry_high:
            return "WAITING_FOR_PULLBACK"
        return "BELOW_ENTRY_ZONE"

    if plan.invalidation_price is not None and current_price >= plan.invalidation_price:
        return "INVALIDATED"
    if plan.target_2 is not None and current_price <= plan.target_2:
        return "TARGET_2_HIT"
    if plan.target_1 is not None and current_price <= plan.target_1:
        return "TARGET_1_HIT"
    if plan.entry_low <= current_price <= plan.entry_high:
        return "ENTRY_ZONE"
    if current_price < plan.entry_low:
        return "WAITING_FOR_PULLBACK"
    return "ABOVE_ENTRY_ZONE"
