from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from state_contracts import DecisionStateSnapshot, MarketStateSnapshot


FORECAST_ENGINE_VERSION = "forecast-snapshot-v2"
FORECAST_STATUSES = {"READY", "DEGRADED", "PROVISIONAL"}
TIME_SCALES = {"MINUTES", "HOURS", "DAYS"}

# Explicit v1 movement baselines by market. These are deliberately simple and
# must be calibrated against realized outcomes; they are not presented as an
# empirically calibrated price model.
_MOVE_SCALE = {
    "Brent": 5.0,
    "Gold": 2.5,
    "Silver": 4.0,
    "DXY": 1.5,
    "Natural Gas": 6.0,
}


def _utc_iso(value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(timezone.utc).isoformat()


def _forecast_id(decision_snapshot_id: str) -> str:
    digest = sha256(str(decision_snapshot_id).encode("utf-8")).hexdigest()[:24]
    return f"forecast:{digest}"


def _time_scale(horizon_hours: float | None) -> str:
    if horizon_hours is None:
        return "HOURS"
    if horizon_hours < 1.0:
        return "MINUTES"
    if horizon_hours <= 24.0:
        return "HOURS"
    return "DAYS"


def _baseline_move_interval(decision: DecisionStateSnapshot) -> tuple[float, float] | None:
    """Translate Decision State strength into an explicit uncalibrated v1 interval.

    This exists so PriceGauger can visualize and measure forecasts before enough
    realized outcomes exist to fit a calibrated movement model. The missing-input
    marker `calibrated_move_model` remains attached to every such forecast.
    """
    if decision.direction not in {"LONG_BIAS", "SHORT_BIAS", "NEUTRAL"}:
        return None
    scale = float(_MOVE_SCALE.get(decision.market, 3.0))
    magnitude = round(scale * abs(float(decision.direction_score)), 4)
    if decision.direction == "LONG_BIAS":
        return round(magnitude * 0.35, 4), magnitude
    if decision.direction == "SHORT_BIAS":
        return -magnitude, round(-magnitude * 0.35, 4)
    half = round(magnitude * 0.5, 4)
    return -half, half


@dataclass(frozen=True, slots=True)
class ForecastSnapshot:
    forecast_id: str
    market: str
    as_of: str
    reference_price: float | None
    direction: str
    direction_score: float
    confidence: float
    expected_move_low_pct: float | None
    expected_move_high_pct: float | None
    horizon_hours: float | None
    time_scale: str
    decision_snapshot_id: str
    information_snapshot_id: str
    market_snapshot_id: str
    status: str
    missing_inputs: tuple[str, ...]
    status_reason: str
    engine_version: str = FORECAST_ENGINE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc_iso(self.as_of))
        if self.status not in FORECAST_STATUSES:
            raise ValueError(f"unsupported forecast status: {self.status}")
        if self.time_scale not in TIME_SCALES:
            raise ValueError(f"unsupported forecast time scale: {self.time_scale}")
        if self.horizon_hours is not None and self.horizon_hours <= 0:
            raise ValueError("forecast horizon must be positive")
        low, high = self.expected_move_low_pct, self.expected_move_high_pct
        if low is not None and high is not None and low > high:
            object.__setattr__(self, "expected_move_low_pct", high)
            object.__setattr__(self, "expected_move_high_pct", low)
        object.__setattr__(self, "missing_inputs", tuple(dict.fromkeys(str(item) for item in self.missing_inputs if str(item))))

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["missing_inputs"] = list(self.missing_inputs)
        return record


def forecast_from_decision(
    decision: DecisionStateSnapshot,
    *,
    market_state: MarketStateSnapshot | None = None,
    additional_missing_inputs: tuple[str, ...] = (),
) -> ForecastSnapshot:
    missing: list[str] = list(additional_missing_inputs)
    if market_state is None or market_state.price is None:
        missing.append("reference_price")
    if not decision.market_snapshot_id or decision.market_snapshot_id == "market-confirmation-pending":
        missing.append("technical_market_state")

    move_low = decision.expected_move_low_pct
    move_high = decision.expected_move_high_pct
    if move_low is None or move_high is None:
        baseline = _baseline_move_interval(decision)
        if baseline is None:
            missing.append("expected_move_interval")
        else:
            move_low, move_high = baseline
            missing.append("calibrated_move_model")

    if decision.horizon_hours is None:
        missing.append("forecast_horizon")

    has_core_forecast = (
        move_low is not None
        and move_high is not None
        and decision.horizon_hours is not None
    )
    if not has_core_forecast:
        status = "PROVISIONAL"
    elif missing:
        status = "DEGRADED"
    else:
        status = "READY"

    return ForecastSnapshot(
        forecast_id=_forecast_id(decision.snapshot_id),
        market=decision.market,
        as_of=decision.as_of,
        reference_price=None if market_state is None else market_state.price,
        direction=decision.direction,
        direction_score=decision.direction_score,
        confidence=decision.confidence,
        expected_move_low_pct=move_low,
        expected_move_high_pct=move_high,
        horizon_hours=decision.horizon_hours,
        time_scale=_time_scale(decision.horizon_hours),
        decision_snapshot_id=decision.snapshot_id,
        information_snapshot_id=decision.information_snapshot_id,
        market_snapshot_id=decision.market_snapshot_id,
        status=status,
        missing_inputs=tuple(missing),
        status_reason=decision.status_reason,
    )
