from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from asset_state_mapping import ASSET_WEIGHTS
from cross_market_state import CrossMarketObservation, CrossMarketStateSnapshot, CrossMarketStateStore
from database import connect
from market_interpretation import STATE_NAMES
from state_contracts import ComponentStatus, InformationStateSnapshot

ENGINE_VERSION = "response-divergence-v1"
SCHEMA_VERSION = "response-divergence-v1"
WINDOWS = ("15m", "1h", "4h")
_WINDOW_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}
# Alignment is explicit: the return reference used by CrossMarketState must point
# back to the Information State observation that generated the expectation.
_ALIGNMENT_TOLERANCES = {
    "15m": timedelta(minutes=2),
    "1h": timedelta(minutes=5),
    "4h": timedelta(minutes=15),
}
_EXPECTATION_DEAD_ZONE = 0.10
_RESPONSE_DEAD_ZONE_PCT = 0.05


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(timezone.utc)


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "response-divergence:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _direction(value: float, *, dead_zone: float) -> str:
    if value > dead_zone:
        return "UP"
    if value < -dead_zone:
        return "DOWN"
    return "FLAT"


def information_expectation_score(information: InformationStateSnapshot, *, market: str) -> float:
    """Map only the new Information State change into the existing asset semantics.

    This deliberately does not use Decision State or technical price confirmation:
    those already contain market-response information and would contaminate a test
    of whether the observed response diverged from the information impulse itself.
    """
    weights = ASSET_WEIGHTS.get(market)
    if not weights:
        raise ValueError(f"unsupported response-divergence market: {market}")
    score = sum(
        float(weights[name]) * float((information.state_change or {}).get(name, 0.0))
        for name in STATE_NAMES
    )
    return max(-1.0, min(1.0, score))


@dataclass(frozen=True, slots=True)
class ResponseDivergenceSnapshot:
    divergence_id: str
    market: str
    window: str
    as_of: str
    information_snapshot_id: str
    information_as_of: str
    cross_market_snapshot_id: str
    cross_market_as_of: str
    expected_score: float
    expected_direction: str
    realized_return_pct: float
    realized_direction: str
    status: str
    alignment_offset_seconds: float
    supporting_observations: dict[str, dict[str, Any]]
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.window not in WINDOWS:
            raise ValueError(f"unsupported window: {self.window}")
        if self.expected_direction not in {"UP", "DOWN"}:
            raise ValueError("expected_direction must be UP or DOWN")
        if self.realized_direction not in {"UP", "DOWN", "FLAT"}:
            raise ValueError("realized_direction must be UP, DOWN or FLAT")
        if self.status not in {"ALIGNED", "DIVERGENT", "UNCONFIRMED"}:
            raise ValueError("status must be ALIGNED, DIVERGENT or UNCONFIRMED")
        object.__setattr__(self, "as_of", _utc(self.as_of).isoformat())
        object.__setattr__(self, "information_as_of", _utc(self.information_as_of).isoformat())
        object.__setattr__(self, "cross_market_as_of", _utc(self.cross_market_as_of).isoformat())
        object.__setattr__(
            self,
            "supporting_observations",
            {name: dict(value) for name, value in self.supporting_observations.items()},
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "ResponseDivergenceSnapshot":
        return cls(**payload)


class ResponseDivergenceStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS response_divergence_snapshots (
                    divergence_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    window TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    information_snapshot_id TEXT NOT NULL,
                    cross_market_snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_response_divergence_market_time
                ON response_divergence_snapshots(market, as_of);
                """
            )

    def save(self, snapshot: ResponseDivergenceSnapshot) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO response_divergence_snapshots(
                    divergence_id, market, window, as_of,
                    information_snapshot_id, cross_market_snapshot_id, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(divergence_id) DO NOTHING
                """,
                (
                    snapshot.divergence_id,
                    snapshot.market,
                    snapshot.window,
                    snapshot.as_of,
                    snapshot.information_snapshot_id,
                    snapshot.cross_market_snapshot_id,
                    snapshot.status,
                    json.dumps(snapshot.to_record(), sort_keys=True),
                ),
            )

    def save_all(self, snapshots: tuple[ResponseDivergenceSnapshot, ...]) -> int:
        for snapshot in snapshots:
            self.save(snapshot)
        return len(snapshots)

    def load_latest(self, *, market: str = "Silver") -> ResponseDivergenceSnapshot | None:
        with connect(self.path) as db:
            row = db.execute(
                """
                SELECT payload_json FROM response_divergence_snapshots
                WHERE market=? ORDER BY as_of DESC LIMIT 1
                """,
                (market,),
            ).fetchone()
        return None if row is None else ResponseDivergenceSnapshot.from_record(json.loads(row["payload_json"]))


def _information_snapshot_from_record(record: dict[str, Any]) -> InformationStateSnapshot:
    component = record.get("component")
    if isinstance(component, dict):
        record["component"] = ComponentStatus(**component)
    for name in ("source_channels", "processed_event_ids", "active_cluster_ids"):
        record[name] = tuple(record.get(name) or ())
    return InformationStateSnapshot(**record)


def _recent_information_snapshots(
    path: str | Path,
    *,
    start: datetime,
    end: datetime,
    limit: int = 500,
) -> tuple[InformationStateSnapshot, ...]:
    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json FROM information_state_snapshots
                WHERE as_of>=? AND as_of<=?
                ORDER BY as_of ASC LIMIT ?
                """,
                (start.isoformat(), end.isoformat(), max(1, int(limit))),
            ).fetchall()
    except Exception:
        return ()
    return tuple(_information_snapshot_from_record(json.loads(row["payload_json"])) for row in rows)


def _observation(snapshot: CrossMarketStateSnapshot, market: str) -> CrossMarketObservation | None:
    return next((item for item in snapshot.observations if item.name == market), None)


def _change_for_window(observation: CrossMarketObservation, window: str) -> float | None:
    return getattr(observation, f"change_{window}")


def _supporting_observations(
    snapshot: CrossMarketStateSnapshot,
    *,
    window: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in snapshot.observations:
        result[item.name] = {
            "kind": item.kind,
            "change": _change_for_window(item, window),
            "window_coverage": item.window_coverage.get(window, "MISSING"),
            "latest_observation_freshness": item.latest_observation_freshness,
        }
    return result


def evaluate_response_divergence(
    information: InformationStateSnapshot,
    cross_market: CrossMarketStateSnapshot,
    *,
    market: str = "Silver",
    window: str,
) -> ResponseDivergenceSnapshot | None:
    """Evaluate one mature, temporally aligned response window.

    Returns None when the expectation is neutral, the market window is invalid, or
    the historical reference used by CrossMarketState does not align with the
    Information State timestamp. No causal explanation is attempted here.
    """
    if window not in WINDOWS:
        raise ValueError(f"unsupported window: {window}")
    expected_score = information_expectation_score(information, market=market)
    expected_direction = _direction(expected_score, dead_zone=_EXPECTATION_DEAD_ZONE)
    if expected_direction == "FLAT":
        return None

    observed = _observation(cross_market, market)
    if observed is None or observed.window_coverage.get(window) != "VALID":
        return None
    realized = _change_for_window(observed, window)
    reference_at = observed.window_reference_at.get(window)
    if realized is None or reference_at is None:
        return None

    alignment_offset = abs((_utc(reference_at) - _utc(information.as_of)).total_seconds())
    if alignment_offset > _ALIGNMENT_TOLERANCES[window].total_seconds():
        return None

    # The CrossMarket snapshot must be a later observation. This prevents a
    # trailing return ending at t0 from being mistaken for the response after t0.
    minimum_maturity = _utc(information.as_of) + _WINDOW_DELTAS[window] - _ALIGNMENT_TOLERANCES[window]
    if _utc(cross_market.as_of) < minimum_maturity:
        return None

    realized_direction = _direction(float(realized), dead_zone=_RESPONSE_DEAD_ZONE_PCT)
    if realized_direction == "FLAT":
        status = "UNCONFIRMED"
    elif realized_direction == expected_direction:
        status = "ALIGNED"
    else:
        status = "DIVERGENT"

    payload = {
        "market": market,
        "window": window,
        "information_snapshot_id": information.snapshot_id,
        "cross_market_snapshot_id": cross_market.snapshot_id,
        "expected_direction": expected_direction,
        "realized_direction": realized_direction,
    }
    return ResponseDivergenceSnapshot(
        divergence_id=_stable_id(payload),
        market=market,
        window=window,
        as_of=cross_market.as_of,
        information_snapshot_id=information.snapshot_id,
        information_as_of=information.as_of,
        cross_market_snapshot_id=cross_market.snapshot_id,
        cross_market_as_of=cross_market.as_of,
        expected_score=round(expected_score, 6),
        expected_direction=expected_direction,
        realized_return_pct=round(float(realized), 6),
        realized_direction=realized_direction,
        status=status,
        alignment_offset_seconds=alignment_offset,
        supporting_observations=_supporting_observations(cross_market, window=window),
    )


def refresh_response_divergences(
    path: str | Path = "pricegauger.db",
    *,
    market: str = "Silver",
    cross_market: CrossMarketStateSnapshot | None = None,
) -> tuple[ResponseDivergenceSnapshot, ...]:
    """Consume the latest persisted CrossMarketState and persist mature evaluations."""
    cross = cross_market or CrossMarketStateStore(path).load_latest(market=market)
    if cross is None:
        return ()
    cross_as_of = _utc(cross.as_of)
    candidates = _recent_information_snapshots(
        path,
        start=cross_as_of - timedelta(hours=5),
        end=cross_as_of,
    )
    if not candidates:
        return ()

    results: list[ResponseDivergenceSnapshot] = []
    for window in WINDOWS:
        observed = _observation(cross, market)
        if observed is None:
            continue
        reference_at = observed.window_reference_at.get(window)
        if reference_at is None:
            continue
        reference = _utc(reference_at)
        tolerance = _ALIGNMENT_TOLERANCES[window].total_seconds()
        aligned = [
            item
            for item in candidates
            if abs((_utc(item.as_of) - reference).total_seconds()) <= tolerance
        ]
        if not aligned:
            continue
        # Prefer the Information State closest to the actual market-window base.
        information = min(
            aligned,
            key=lambda item: abs((_utc(item.as_of) - reference).total_seconds()),
        )
        result = evaluate_response_divergence(
            information,
            cross,
            market=market,
            window=window,
        )
        if result is not None:
            results.append(result)

    snapshots = tuple(results)
    ResponseDivergenceStore(path).save_all(snapshots)
    return snapshots
