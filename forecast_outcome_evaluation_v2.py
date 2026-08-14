from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence
from uuid import UUID

from database import connect


MAX_ACTIVE_GAP_SECONDS_V2 = 30 * 60


@dataclass(frozen=True, slots=True)
class ForecastClaimV2:
    forecast_id: UUID
    market_id: int
    as_of: str
    horizon_seconds: int
    baseline_return: float | None
    composed_return: float | None
    lower_return: float | None
    upper_return: float | None


@dataclass(frozen=True, slots=True)
class ForecastOutcomeV2:
    forecast_id: UUID
    matured_at: str
    reference_price: float
    realized_terminal_price: float
    realized_return: float
    absolute_error: float | None
    signed_error: float | None
    status: str


PricePointV2 = tuple[str, float]
PricePathResolverV2 = Callable[[ForecastClaimV2], Sequence[PricePointV2]]


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_points(points: Iterable[PricePointV2], *, as_of: str) -> list[tuple[datetime, float]]:
    floor = _utc(as_of)
    normalized: dict[datetime, float] = {}
    for stamp, price in points:
        try:
            observed = _utc(stamp)
            numeric = float(price)
        except (TypeError, ValueError, OverflowError):
            continue
        if observed < floor or numeric <= 0:
            continue
        normalized[observed] = numeric
    return sorted(normalized.items(), key=lambda item: item[0])


def evaluate_forecast_claim_v2(
    claim: ForecastClaimV2,
    points: Iterable[PricePointV2],
    *,
    max_active_gap_seconds: int = MAX_ACTIVE_GAP_SECONDS_V2,
) -> ForecastOutcomeV2 | None:
    """Evaluate one immutable v2 forecast against canonical realized prices.

    Horizon progress is measured in active market time. Gaps longer than the
    configured threshold (weekends, session breaks, provider outages) do not
    consume horizon time. The first available observation at/after ``as_of`` is
    the frozen reference price; the first observation reaching the requested
    active horizon is the terminal observation.

    ``None`` means the forecast has not matured yet and must remain unevaluated.
    """
    if claim.horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")

    normalized = _normalized_points(points, as_of=claim.as_of)
    if not normalized:
        return None

    _, reference_price = normalized[0]
    active_seconds = 0.0
    cursor = _utc(claim.as_of)
    terminal_at: datetime | None = None
    terminal_price: float | None = None
    max_gap = max(60, int(max_active_gap_seconds))

    for observed, price in normalized:
        gap_seconds = max(0.0, (observed - cursor).total_seconds())
        if gap_seconds <= max_gap:
            active_seconds += gap_seconds
        cursor = observed
        if active_seconds >= int(claim.horizon_seconds):
            terminal_at = observed
            terminal_price = price
            break

    if terminal_at is None or terminal_price is None:
        return None

    realized_return = (terminal_price / reference_price) - 1.0
    predicted = claim.composed_return
    signed_error = None if predicted is None else realized_return - float(predicted)
    absolute_error = None if signed_error is None else abs(signed_error)

    return ForecastOutcomeV2(
        forecast_id=claim.forecast_id,
        matured_at=terminal_at.isoformat(),
        reference_price=reference_price,
        realized_terminal_price=terminal_price,
        realized_return=realized_return,
        absolute_error=absolute_error,
        signed_error=signed_error,
        status="COMPLETE",
    )


def interval_hit_v2(claim: ForecastClaimV2, outcome: ForecastOutcomeV2) -> bool | None:
    """Return interval coverage without storing a redundant derived column."""
    if claim.lower_return is None or claim.upper_return is None:
        return None
    return float(claim.lower_return) <= outcome.realized_return <= float(claim.upper_return)


def direction_hit_v2(claim: ForecastClaimV2, outcome: ForecastOutcomeV2) -> bool | None:
    """Return directional correctness from the frozen composed forecast."""
    predicted = claim.composed_return
    if predicted is None:
        return None
    predicted = float(predicted)
    if predicted > 0:
        return outcome.realized_return > 0
    if predicted < 0:
        return outcome.realized_return < 0
    return outcome.realized_return == 0


def persist_forecast_outcome_v2(outcome: ForecastOutcomeV2) -> None:
    """Freeze one completed objective outcome. Completed outcomes are immutable."""
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_forecast_outcomes
                (forecast_id, matured_at, realized_terminal_price, realized_return,
                 absolute_error, signed_error, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (forecast_id) DO NOTHING
            """,
            (
                str(outcome.forecast_id),
                outcome.matured_at,
                outcome.realized_terminal_price,
                outcome.realized_return,
                outcome.absolute_error,
                outcome.signed_error,
                outcome.status,
            ),
        )


def load_unevaluated_forecast_claims_v2(*, limit: int = 500) -> tuple[ForecastClaimV2, ...]:
    """Load immutable forecast claims that do not yet have a frozen outcome."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT f.forecast_id, f.market_id, f.as_of, f.horizon_seconds,
                   f.baseline_return, f.composed_return, f.lower_return, f.upper_return
            FROM pg_v2_forecasts f
            LEFT JOIN pg_v2_forecast_outcomes o ON o.forecast_id = f.forecast_id
            WHERE o.forecast_id IS NULL
            ORDER BY f.as_of ASC, f.horizon_seconds ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()

    claims: list[ForecastClaimV2] = []
    for row in rows:
        def get(key: str, index: int):
            return row[key] if isinstance(row, dict) else row[index]

        claims.append(
            ForecastClaimV2(
                forecast_id=UUID(str(get("forecast_id", 0))),
                market_id=int(get("market_id", 1)),
                as_of=str(get("as_of", 2)),
                horizon_seconds=int(get("horizon_seconds", 3)),
                baseline_return=None if get("baseline_return", 4) is None else float(get("baseline_return", 4)),
                composed_return=None if get("composed_return", 5) is None else float(get("composed_return", 5)),
                lower_return=None if get("lower_return", 6) is None else float(get("lower_return", 6)),
                upper_return=None if get("upper_return", 7) is None else float(get("upper_return", 7)),
            )
        )
    return tuple(claims)


def refresh_forecast_outcomes_v2(
    *,
    price_path_resolver: PricePathResolverV2,
    limit: int = 500,
    persist: bool = True,
) -> tuple[ForecastOutcomeV2, ...]:
    """Evaluate every currently mature v2 forecast exactly once.

    Price resolution is injected deliberately: forecasts are market-level claims,
    while raw v2 bars preserve exact instrument/contract identity. A future
    continuous-market adapter can therefore define rollover semantics without
    contaminating the objective evaluation contract itself.
    """
    completed: list[ForecastOutcomeV2] = []
    for claim in load_unevaluated_forecast_claims_v2(limit=limit):
        outcome = evaluate_forecast_claim_v2(claim, price_path_resolver(claim))
        if outcome is None:
            continue
        if persist:
            persist_forecast_outcome_v2(outcome)
        completed.append(outcome)
    return tuple(completed)
