"""Causal, explainable multi-market forecast research for TECH100.

An isolated linear baseline, not a discovered trading edge. Inputs use price
percentage changes for Gold/Brent/DXY and basis-point *yield* changes for US2/10/30.
Two independent fits are required: longer regime and short impulse. No market
data calls, broker calls or trading state exist here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from statistics import mean
from typing import Mapping, Sequence

from tech100_four_channel_synthesis_v1 import ChannelSignal, IMPULSE, REGIME

FACTORS = ("Gold", "Brent", "DXY", "US2Y", "US10Y", "US30Y")
PRICE_PCT = "PRICE_PCT"
YIELD_BP = "YIELD_BP"
PRICE_PROXY_PCT = "PRICE_PROXY_PCT"
DEFAULT_FACTOR_UNITS = {
    "Gold": PRICE_PCT, "Brent": PRICE_PCT, "DXY": PRICE_PCT,
    "US2Y": YIELD_BP, "US10Y": YIELD_BP, "US30Y": YIELD_BP,
}


def _validate_units(values: Mapping[str, str]) -> None:
    if set(values) != set(FACTORS):
        raise ValueError("factor units must name all six factors")
    for factor, unit in values.items():
        accepted = {PRICE_PCT} if factor in ("Gold", "Brent", "DXY") else {YIELD_BP, PRICE_PROXY_PCT}
        if unit not in accepted:
            raise ValueError(f"invalid factor unit for {factor}")


def _utc(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("time must include UTC offset")
    return at.astimezone(timezone.utc)


@dataclass(frozen=True)
class LabeledMarketMove:
    """A historical row constructed from quotes available at ``observed_at``.

    Gold/Brent/DXY inputs are percentage changes. Rate inputs are yield-basis-
    point changes, or explicitly selected percentage PRICE PROXY returns for
    Treasury futures/CFDs. The two units may never be blended within one fit.
    ``future_at`` is when the TECH100 return became knowable; it must remain
    before the first holdout decision if used for training.
    """
    observed_at: datetime
    future_at: datetime
    factors: Mapping[str, float]
    future_tech100_pct: float
    factor_units: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_FACTOR_UNITS))

    def __post_init__(self) -> None:
        if _utc(self.future_at) <= _utc(self.observed_at):
            raise ValueError("future must follow feature observation")
        if set(self.factors) != set(FACTORS):
            raise ValueError("all six factor observations required")
        _validate_units(self.factor_units)
        if any(not isfinite(value) for value in self.factors.values()) or not isfinite(self.future_tech100_pct):
            raise ValueError("nonfinite market observation")


@dataclass(frozen=True)
class FactorReading:
    name: str
    value: float
    observed_at: datetime
    unit: str | None = None


@dataclass(frozen=True)
class CrossMarketModel:
    channel: str
    horizon_minutes: int
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    train_count: int
    holdout_count: int
    holdout_mae_pct: float
    zero_baseline_mae_pct: float
    holdout_direction_accuracy: float
    factor_units: Mapping[str, str]

    @property
    def holdout_better_than_zero(self) -> bool:
        return self.holdout_mae_pct < self.zero_baseline_mae_pct


@dataclass(frozen=True)
class FactorForecast:
    signal: ChannelSignal
    intercept_pct: float
    contributions_pct: Mapping[str, float]
    shock_factors: tuple[str, ...]


def _solve(matrix: list[list[float]], vector: list[float]) -> tuple[float, ...]:
    """Small ridge normal equations with pivoting; no optional ML dependency."""
    size = len(vector)
    a = [list(row) + [rhs] for row, rhs in zip(matrix, vector)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda idx: abs(a[idx][col]))
        a[col], a[pivot] = a[pivot], a[col]
        if abs(a[col][col]) < 1e-12:
            raise ValueError("singular regression system")
        for idx in range(col + 1, size):
            scale = a[idx][col] / a[col][col]
            for j in range(col, size + 1):
                a[idx][j] -= scale * a[col][j]
    result = [0.0] * size
    for idx in range(size - 1, -1, -1):
        result[idx] = (a[idx][size] - sum(a[idx][col] * result[col]
                                              for col in range(idx + 1, size))) / a[idx][idx]
    return tuple(result)


def fit_crossmarket_model(
    observations: Sequence[LabeledMarketMove],
    *,
    channel: str,
    horizon_minutes: int,
    train_fraction: float = 0.7,
    ridge_penalty: float = 5.0,
    minimum_train: int = 40,
    minimum_holdout: int = 15,
) -> CrossMarketModel:
    """Chronological fit with outcome-overlap purge and frozen OOS evaluation."""
    if channel not in (REGIME, IMPULSE) or horizon_minutes <= 0:
        raise ValueError("invalid channel or horizon")
    if not 0.5 <= train_fraction <= 0.85 or ridge_penalty <= 0:
        raise ValueError("invalid fit settings")
    rows = sorted(observations, key=lambda row: _utc(row.observed_at))
    units = dict(rows[0].factor_units) if rows else dict(DEFAULT_FACTOR_UNITS)
    if any(dict(row.factor_units) != units for row in rows):
        raise ValueError("mixed yield-basis-point and Treasury-price-proxy units")
    if len({_utc(row.observed_at) for row in rows}) != len(rows):
        raise ValueError("duplicate decision timestamps")
    for row in rows:
        if _utc(row.future_at) - _utc(row.observed_at) != timedelta(minutes=horizon_minutes):
            raise ValueError("inconsistent label horizon")
    split = int(len(rows) * train_fraction)
    holdout = rows[split:]
    if len(holdout) < minimum_holdout:
        raise ValueError("insufficient holdout history")
    first_holdout_at = _utc(holdout[0].observed_at)
    # Predictions in training cannot use labels realized after the holdout begins.
    train = [row for row in rows[:split] if _utc(row.future_at) < first_holdout_at]
    if len(train) < minimum_train:
        raise ValueError("insufficient purged training history")

    feature_means = tuple(mean(row.factors[factor] for row in train) for factor in FACTORS)
    scales = tuple(max(sqrt(mean((row.factors[factor] - feature_means[i]) ** 2
                                 for row in train)), 1e-9)
                   for i, factor in enumerate(FACTORS))
    normalized = [[1.0] + [(row.factors[factor] - feature_means[i]) / scales[i]
                             for i, factor in enumerate(FACTORS)] for row in train]
    count = len(FACTORS) + 1
    normal = [[sum(row[i] * row[j] for row in normalized) for j in range(count)]
              for i in range(count)]
    for i in range(1, count):
        normal[i][i] += ridge_penalty
    right = [sum(x[i] * row.future_tech100_pct for x, row in zip(normalized, train))
             for i in range(count)]
    fitted = _solve(normal, right)

    def pred(row: LabeledMarketMove) -> float:
        return fitted[0] + sum(fitted[i + 1] * (row.factors[factor] - feature_means[i]) / scales[i]
                               for i, factor in enumerate(FACTORS))

    mae = mean(abs(pred(row) - row.future_tech100_pct) for row in holdout)
    base_mae = mean(abs(row.future_tech100_pct) for row in holdout)
    directional_accuracy = mean((pred(row) > 0) == (row.future_tech100_pct > 0)
                                for row in holdout)
    return CrossMarketModel(channel, horizon_minutes, feature_means, scales,
                            fitted[1:], fitted[0], len(train), len(holdout),
                            mae, base_mae, directional_accuracy, units)


def forecast_crossmarket(
    model: CrossMarketModel,
    *,
    at: datetime,
    readings: Sequence[FactorReading],
    historical_data_quality_verified: bool = False,
    shock_z_threshold: float = 2.0,
) -> FactorForecast:
    """Return an inspectable forecast, abstaining on stale/unavailable inputs.

    Historical validation *and* verified live/historical instrument matching are
    both required for the signal to be eligible for PAPER synthesis. No LIVE.
    """
    at = _utc(at)
    by_name = {item.name: item for item in readings}
    if len(readings) != len(by_name) or set(by_name) != set(FACTORS):
        raise ValueError("exact Gold/Brent/DXY/US2Y/US10Y/US30Y readings required")
    if any((item.unit or DEFAULT_FACTOR_UNITS[item.name]) != model.factor_units[item.name]
           for item in readings):
        raise ValueError("live factor unit differs from historical fitted unit")
    max_age = timedelta(minutes=2 if model.channel == IMPULSE else 10)
    if any(not isfinite(item.value) or not timedelta(0) <= at - _utc(item.observed_at) <= max_age
           for item in readings):
        raise ValueError("nonfinite, stale or future factor input")
    standardized = {factor: (by_name[factor].value - model.means[i]) / model.scales[i]
                    for i, factor in enumerate(FACTORS)}
    contributions = {factor: standardized[factor] * model.coefficients[i]
                     for i, factor in enumerate(FACTORS)}
    shocks = tuple(factor for factor in FACTORS if abs(standardized[factor]) >= shock_z_threshold)
    predictive = model.holdout_better_than_zero and historical_data_quality_verified
    if model.channel == IMPULSE and not shocks:
        predictive = False
    estimate = model.intercept + sum(contributions.values())
    confidence = max(0.0, min(1.0, 1 - model.holdout_mae_pct /
                              max(model.zero_baseline_mae_pct, 1e-12)))
    signal = ChannelSignal(model.channel, at, model.horizon_minutes,
                           estimate if predictive else None, confidence,
                           tuple(f"{name}:{value:+.4f}pct" for name, value in contributions.items()),
                           validated_out_of_sample=predictive)
    return FactorForecast(signal, model.intercept, contributions, shocks)
