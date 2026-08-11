from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from database import connect
from market_history_store import MarketHistoryStore

ENGINE_VERSION = "cross-market-state-v1"
SCHEMA_VERSION = "cross-market-state-v1"
RETURN_MARKETS = ("Silver", "Gold", "Brent", "DXY")
YIELD_TENORS = ("US2Y", "US10Y", "US30Y")
WINDOWS = ("15m", "1h", "4h")
_WINDOW_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}
# Canonical realtime history is normally one-minute data. A current observation
# older than five minutes is too old for a state that may later support 15m
# response-divergence analysis, even if longer windows could still be computed.
_LATEST_FRESHNESS = timedelta(minutes=5)
# A return is valid only when the historical reference observation is genuinely
# close to the requested horizon. These tolerances are explicit contract values,
# not a silent "last point before target" fallback across session/data gaps.
_WINDOW_TOLERANCES = {
    "15m": timedelta(minutes=2),
    "1h": timedelta(minutes=5),
    "4h": timedelta(minutes=15),
}


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(timezone.utc)


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "cross-market-state:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _missing_window_status() -> dict[str, str]:
    return {window: "MISSING" for window in WINDOWS}


def _missing_window_references() -> dict[str, str | None]:
    return {window: None for window in WINDOWS}


def _missing_window_offsets() -> dict[str, float | None]:
    return {window: None for window in WINDOWS}


@dataclass(frozen=True, slots=True)
class CrossMarketObservation:
    name: str
    kind: str
    observed_at: str | None
    value: float | None
    change_15m: float | None
    change_1h: float | None
    change_4h: float | None
    latest_observation_freshness: str
    provider: str
    instrument: str
    latest_observation_age_seconds: float | None = None
    window_coverage: dict[str, str] = field(default_factory=_missing_window_status)
    window_reference_at: dict[str, str | None] = field(default_factory=_missing_window_references)
    window_reference_offset_seconds: dict[str, float | None] = field(default_factory=_missing_window_offsets)
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"RETURN_PCT", "YIELD_PCT"}:
            raise ValueError("kind must be RETURN_PCT or YIELD_PCT")
        if self.latest_observation_freshness not in {"FRESH", "STALE", "MISSING"}:
            raise ValueError("latest_observation_freshness must be FRESH, STALE or MISSING")
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _utc(self.observed_at).isoformat())
        coverage = dict(self.window_coverage)
        references = dict(self.window_reference_at)
        offsets = dict(self.window_reference_offset_seconds)
        if set(coverage) != set(WINDOWS):
            raise ValueError(f"window_coverage must contain exactly {WINDOWS}")
        if set(references) != set(WINDOWS):
            raise ValueError(f"window_reference_at must contain exactly {WINDOWS}")
        if set(offsets) != set(WINDOWS):
            raise ValueError(f"window_reference_offset_seconds must contain exactly {WINDOWS}")
        if any(status not in {"VALID", "MISSING"} for status in coverage.values()):
            raise ValueError("window coverage must be VALID or MISSING")
        normalized_references = {
            key: None if value is None else _utc(value).isoformat()
            for key, value in references.items()
        }
        object.__setattr__(self, "window_coverage", coverage)
        object.__setattr__(self, "window_reference_at", normalized_references)
        object.__setattr__(self, "window_reference_offset_seconds", offsets)

    @property
    def freshness(self) -> str:
        """Compatibility alias for callers that only need latest-point freshness."""
        return self.latest_observation_freshness

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CrossMarketStateSnapshot:
    snapshot_id: str
    market: str
    as_of: str
    observations: tuple[CrossMarketObservation, ...]
    curve_spreads_bp: dict[str, float | None]
    curve_changes_bp: dict[str, dict[str, float | None]]
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc(self.as_of).isoformat())
        object.__setattr__(self, "curve_spreads_bp", dict(self.curve_spreads_bp))
        object.__setattr__(self, "curve_changes_bp", {key: dict(value) for key, value in self.curve_changes_bp.items()})

    def to_record(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "market": self.market,
            "as_of": self.as_of,
            "observations": [item.to_record() for item in self.observations],
            "curve_spreads_bp": dict(self.curve_spreads_bp),
            "curve_changes_bp": {key: dict(value) for key, value in self.curve_changes_bp.items()},
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "CrossMarketStateSnapshot":
        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            market=str(payload["market"]),
            as_of=str(payload["as_of"]),
            observations=tuple(CrossMarketObservation(**item) for item in payload.get("observations", ())),
            curve_spreads_bp=dict(payload.get("curve_spreads_bp") or {}),
            curve_changes_bp={key: dict(value) for key, value in (payload.get("curve_changes_bp") or {}).items()},
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            engine_version=str(payload.get("engine_version") or ENGINE_VERSION),
        )


class CrossMarketStateStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cross_market_state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_cross_market_state_market_time
                ON cross_market_state_snapshots(market, as_of);
                """
            )

    def save(self, snapshot: CrossMarketStateSnapshot) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO cross_market_state_snapshots(snapshot_id, market, as_of, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.market,
                    snapshot.as_of,
                    json.dumps(snapshot.to_record(), sort_keys=True),
                ),
            )

    def load_latest(self, *, market: str) -> CrossMarketStateSnapshot | None:
        with connect(self.path) as db:
            row = db.execute(
                """
                SELECT payload_json FROM cross_market_state_snapshots
                WHERE market=? ORDER BY as_of DESC LIMIT 1
                """,
                (market,),
            ).fetchone()
        if row is None:
            return None
        return CrossMarketStateSnapshot.from_record(json.loads(row["payload_json"]))


def _nearest_reference(
    points: tuple[tuple[str, float], ...], target: datetime
) -> tuple[datetime, float, float] | None:
    candidates = [(_utc(stamp), float(value)) for stamp, value in points]
    if not candidates:
        return None
    observed, value = min(candidates, key=lambda item: abs((item[0] - target).total_seconds()))
    return observed, value, abs((observed - target).total_seconds())


def _market_observation(history: MarketHistoryStore, market: str, *, as_of: datetime) -> CrossMarketObservation:
    start = as_of - timedelta(hours=5)
    points = history.load_range(market=market, start=start, end=as_of, limit=10000)
    if not points:
        return CrossMarketObservation(
            name=market,
            kind="RETURN_PCT",
            observed_at=None,
            value=None,
            change_15m=None,
            change_1h=None,
            change_4h=None,
            latest_observation_freshness="MISSING",
            provider="canonical-market-history",
            instrument=market,
            detail="No canonical price history available.",
        )

    latest_at = _utc(points[-1][0])
    latest = float(points[-1][1])
    age_seconds = max(0.0, (as_of - latest_at).total_seconds())
    latest_freshness = "FRESH" if age_seconds <= _LATEST_FRESHNESS.total_seconds() else "STALE"

    changes: dict[str, float | None] = {}
    coverage = _missing_window_status()
    references = _missing_window_references()
    offsets = _missing_window_offsets()
    for label, delta in _WINDOW_DELTAS.items():
        target = as_of - delta
        candidate = _nearest_reference(points, target)
        if candidate is not None:
            base_at, base_value, offset_seconds = candidate
            references[label] = base_at.isoformat()
            offsets[label] = offset_seconds
        else:
            base_value = 0.0
            offset_seconds = float("inf")
        valid_reference = offset_seconds <= _WINDOW_TOLERANCES[label].total_seconds()
        if latest_freshness == "FRESH" and valid_reference and base_value != 0:
            changes[label] = (latest / base_value - 1.0) * 100.0
            coverage[label] = "VALID"
        else:
            changes[label] = None

    missing_labels = [label for label in WINDOWS if coverage[label] == "MISSING"]
    detail = ""
    if latest_freshness == "STALE":
        detail = "Latest canonical observation is stale; all return windows are invalid."
    elif missing_labels:
        detail = "Missing temporally valid reference for: " + ", ".join(missing_labels) + "."

    return CrossMarketObservation(
        name=market,
        kind="RETURN_PCT",
        observed_at=latest_at.isoformat(),
        value=latest,
        change_15m=changes["15m"],
        change_1h=changes["1h"],
        change_4h=changes["4h"],
        latest_observation_freshness=latest_freshness,
        provider="canonical-market-history",
        instrument=market,
        latest_observation_age_seconds=age_seconds,
        window_coverage=coverage,
        window_reference_at=references,
        window_reference_offset_seconds=offsets,
        detail=detail,
    )


def _missing_yield_observation(tenor: str) -> CrossMarketObservation:
    return CrossMarketObservation(
        name=tenor,
        kind="YIELD_PCT",
        observed_at=None,
        value=None,
        change_15m=None,
        change_1h=None,
        change_4h=None,
        latest_observation_freshness="MISSING",
        provider="unconfigured",
        instrument=tenor,
        detail="Verified Treasury yield feed not configured; futures prices must not be treated as yields.",
    )


def _curve_payload(observations: tuple[CrossMarketObservation, ...]) -> tuple[dict[str, float | None], dict[str, dict[str, float | None]]]:
    by_name = {item.name: item for item in observations}
    pairs = {"2s10s": ("US2Y", "US10Y"), "10s30s": ("US10Y", "US30Y"), "2s30s": ("US2Y", "US30Y")}
    spreads: dict[str, float | None] = {}
    changes: dict[str, dict[str, float | None]] = {}
    for label, (short_name, long_name) in pairs.items():
        short = by_name[short_name]
        long = by_name[long_name]
        spreads[label] = None if short.value is None or long.value is None else (long.value - short.value) * 100.0
        changes[label] = {}
        for window, attr in (("15m", "change_15m"), ("1h", "change_1h"), ("4h", "change_4h")):
            short_change = getattr(short, attr)
            long_change = getattr(long, attr)
            valid = short.window_coverage[window] == "VALID" and long.window_coverage[window] == "VALID"
            changes[label][window] = None if not valid or short_change is None or long_change is None else long_change - short_change
    return spreads, changes


def build_cross_market_state(
    *,
    path: str | Path = "pricegauger.db",
    market: str = "Silver",
    as_of: str | datetime | None = None,
    yield_observations: tuple[CrossMarketObservation, ...] | None = None,
) -> CrossMarketStateSnapshot:
    now = _utc(as_of or datetime.now(timezone.utc))
    history = MarketHistoryStore(path)
    market_observations = tuple(_market_observation(history, name, as_of=now) for name in RETURN_MARKETS)
    yields = yield_observations or tuple(_missing_yield_observation(name) for name in YIELD_TENORS)
    if tuple(item.name for item in yields) != YIELD_TENORS:
        raise ValueError(f"yield observations must be ordered as {YIELD_TENORS}")
    observations = market_observations + tuple(yields)
    spreads, curve_changes = _curve_payload(observations)
    payload = {
        "market": market,
        "as_of": now.isoformat(),
        "observations": [item.to_record() for item in observations],
        "curve_spreads_bp": spreads,
        "curve_changes_bp": curve_changes,
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
    }
    return CrossMarketStateSnapshot(
        snapshot_id=_stable_id(payload),
        market=market,
        as_of=now.isoformat(),
        observations=observations,
        curve_spreads_bp=spreads,
        curve_changes_bp=curve_changes,
    )
