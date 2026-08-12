from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from database import connect
from forecast_error import ForecastErrorObservation


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ForecastAdaptationContext:
    """Descriptive context observed while one immutable forecast was alive.

    This is deliberately not a score and is never written back into forecast,
    Decision State, confidence, calibration or TransmissionState. It only answers
    whether already-persisted response/transmission observations occurred between
    forecast origin and outcome evaluation.
    """

    error_id: str
    response_count: int
    divergent_count: int
    aligned_count: int
    unconfirmed_count: int
    transmission_count: int
    resolved_count: int
    unresolved_count: int
    dominant_channels: tuple[str, ...]

    @property
    def saw_divergence(self) -> bool:
        return self.divergent_count > 0

    @property
    def saw_unresolved_transmission(self) -> bool:
        return self.unresolved_count > 0

    @property
    def has_context(self) -> bool:
        return self.response_count > 0 or self.transmission_count > 0


def _load_payloads(
    path: str | Path,
    *,
    table: str,
    market: str,
    start: datetime,
    end: datetime,
) -> tuple[dict, ...]:
    if table not in {"response_divergence_snapshots", "transmission_state_snapshots"}:
        raise ValueError(f"unsupported diagnostics table: {table}")
    try:
        with connect(path) as db:
            rows = db.execute(
                f"""
                SELECT payload_json FROM {table}
                WHERE market=? AND as_of>=? AND as_of<=?
                ORDER BY as_of ASC
                """,
                (market, start.isoformat(), end.isoformat()),
            ).fetchall()
    except Exception:
        return ()
    return tuple(json.loads(row["payload_json"]) for row in rows)


def load_adaptation_contexts(
    path: str | Path,
    observations: Iterable[ForecastErrorObservation],
) -> dict[str, ForecastAdaptationContext]:
    """Join forecast errors to observations made during each forecast lifetime.

    Association is purely temporal and market-bound. A context marker therefore
    means "this was observed while the forecast was alive", never "this caused the
    forecast error".
    """

    errors = tuple(observations)
    if not errors:
        return {}

    result: dict[str, ForecastAdaptationContext] = {}
    by_market: dict[str, list[ForecastErrorObservation]] = {}
    for item in errors:
        by_market.setdefault(item.market, []).append(item)

    for market, market_errors in by_market.items():
        start = min(_utc(item.forecast_as_of) for item in market_errors)
        end = max(_utc(item.outcome_evaluated_at) for item in market_errors)
        responses = _load_payloads(
            path,
            table="response_divergence_snapshots",
            market=market,
            start=start,
            end=end,
        )
        transmissions = _load_payloads(
            path,
            table="transmission_state_snapshots",
            market=market,
            start=start,
            end=end,
        )

        for error in market_errors:
            window_start = _utc(error.forecast_as_of)
            window_end = _utc(error.outcome_evaluated_at)
            response_rows = [
                row for row in responses
                if window_start <= _utc(str(row.get("as_of"))) <= window_end
            ]
            transmission_rows = [
                row for row in transmissions
                if window_start <= _utc(str(row.get("as_of"))) <= window_end
            ]

            statuses = [str(row.get("status", "")) for row in response_rows]
            resolutions = [str(row.get("resolution_status", "")) for row in transmission_rows]
            channels = tuple(
                sorted(
                    {
                        str(row.get("dominant_channel"))
                        for row in transmission_rows
                        if row.get("dominant_channel")
                    }
                )
            )
            result[error.error_id] = ForecastAdaptationContext(
                error_id=error.error_id,
                response_count=len(response_rows),
                divergent_count=sum(status == "DIVERGENT" for status in statuses),
                aligned_count=sum(status == "ALIGNED" for status in statuses),
                unconfirmed_count=sum(status == "UNCONFIRMED" for status in statuses),
                transmission_count=len(transmission_rows),
                resolved_count=sum(status == "RESOLVED" for status in resolutions),
                unresolved_count=sum(status == "UNRESOLVED" for status in resolutions),
                dominant_channels=channels,
            )

    return result
