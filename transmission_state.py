from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from database import connect
from response_divergence import ResponseDivergenceSnapshot


ENGINE_VERSION = "transmission-state-v1"
SCHEMA_VERSION = "transmission-state-v1"
CHANNELS = (
    "SAFE_HAVEN",
    "RATES_FX",
    "ENERGY_INFLATION",
    "INDUSTRIAL_GROWTH",
    "RISK_LIQUIDITY",
)
_RESOLUTION_THRESHOLD = 0.60
_RESOLUTION_MARGIN = 0.10
_MARKET_DEAD_ZONE_PCT = 0.05


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "transmission-state:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _sign(value: float | None, *, dead_zone: float = _MARKET_DEAD_ZONE_PCT) -> int:
    if value is None:
        return 0
    if value > dead_zone:
        return 1
    if value < -dead_zone:
        return -1
    return 0


def _change(divergence: ResponseDivergenceSnapshot, name: str) -> float | None:
    item = divergence.supporting_observations.get(name)
    if not item or item.get("window_coverage") != "VALID":
        return None
    value = item.get("change")
    return None if value is None else float(value)


def _direction_sign(direction: str) -> int:
    if direction == "UP":
        return 1
    if direction == "DOWN":
        return -1
    return 0


def _channel_evidence(divergence: ResponseDivergenceSnapshot) -> dict[str, dict[str, Any]]:
    silver_sign = _direction_sign(divergence.realized_direction)
    gold_change = _change(divergence, "Gold")
    brent_change = _change(divergence, "Brent")
    dxy_change = _change(divergence, "DXY")
    yield_changes = {name: _change(divergence, name) for name in ("US2Y", "US10Y", "US30Y")}

    gold_pressure = _sign(gold_change)
    dxy_pressure = -_sign(dxy_change)
    yield_pressures = {name: -_sign(value) for name, value in yield_changes.items()}
    available_yield_pressures = [value for value in yield_pressures.values() if value != 0]

    evidence: dict[str, dict[str, Any]] = {}

    safe_score = 0.0 if gold_pressure == 0 else 0.65 * gold_pressure
    evidence["SAFE_HAVEN"] = {
        "score": round(safe_score, 3),
        "signals": [] if gold_change is None else [f"Gold {gold_change:+.3f}% over {divergence.window}"],
        "missing_inputs": [] if gold_change is not None else ["Gold"],
        "interpretation": "Gold is used only as a broad precious-metals/safe-haven confirmation signal.",
    }

    rates_score = 0.0
    rates_signals: list[str] = []
    rates_missing: list[str] = []
    if dxy_pressure != 0:
        rates_score += 0.45 * dxy_pressure
        rates_signals.append(f"DXY {dxy_change:+.3f}% over {divergence.window}")
    elif dxy_change is None:
        rates_missing.append("DXY")
    for name, pressure in yield_pressures.items():
        change = yield_changes[name]
        if change is None:
            rates_missing.append(name)
        elif pressure != 0:
            rates_score += (0.55 / 3.0) * pressure
            rates_signals.append(f"{name} {change:+.4f} over {divergence.window}")
    evidence["RATES_FX"] = {
        "score": round(max(-1.0, min(1.0, rates_score)), 3),
        "signals": rates_signals,
        "missing_inputs": rates_missing,
        "interpretation": "Higher DXY/yields imply negative Silver pressure; lower DXY/yields imply positive pressure.",
    }

    brent_sign = _sign(brent_change)
    macro_pressure_values = ([dxy_pressure] if dxy_pressure else []) + available_yield_pressures
    macro_pressure = 0.0
    if macro_pressure_values:
        macro_pressure = sum(macro_pressure_values) / len(macro_pressure_values)
    energy_score = 0.0
    energy_signals: list[str] = []
    if brent_change is not None:
        energy_signals.append(f"Brent {brent_change:+.3f}% over {divergence.window}")
    if brent_sign > 0 and macro_pressure < 0:
        energy_score = -min(0.85, 0.45 + 0.40 * abs(macro_pressure))
    elif brent_sign < 0 and macro_pressure > 0:
        energy_score = min(0.85, 0.45 + 0.40 * abs(macro_pressure))
    elif brent_sign != 0:
        # Oil alone is not enough to infer the inflation/rates transmission channel.
        energy_score = -0.20 if brent_sign > 0 else 0.20
    evidence["ENERGY_INFLATION"] = {
        "score": round(energy_score, 3),
        "signals": energy_signals + rates_signals,
        "missing_inputs": (["Brent"] if brent_change is None else []) + rates_missing,
        "interpretation": "Brent requires confirming FX/rate pressure before energy-inflation can resolve as dominant.",
    }

    industrial_score = 0.0
    industrial_signals: list[str] = []
    if silver_sign < 0 and gold_pressure > 0:
        industrial_score = -0.45
        industrial_signals.append("Silver fell while Gold rose")
    elif silver_sign > 0 and gold_pressure < 0:
        industrial_score = 0.45
        industrial_signals.append("Silver rose while Gold fell")
    evidence["INDUSTRIAL_GROWTH"] = {
        "score": industrial_score,
        "signals": industrial_signals,
        "missing_inputs": ["dedicated_growth_proxy"],
        "interpretation": "Gold/Silver relative performance is weak evidence only; v1 has no dedicated growth proxy.",
    }

    liquidity_score = 0.0
    liquidity_signals: list[str] = []
    if dxy_pressure < 0 and gold_pressure < 0 and silver_sign < 0:
        liquidity_score = -0.75
        liquidity_signals.append("DXY strengthened while Gold and Silver fell")
    elif dxy_pressure > 0 and gold_pressure > 0 and silver_sign > 0:
        liquidity_score = 0.65
        liquidity_signals.append("DXY weakened while Gold and Silver rose")
    evidence["RISK_LIQUIDITY"] = {
        "score": liquidity_score,
        "signals": liquidity_signals,
        "missing_inputs": [name for name, value in (("DXY", dxy_change), ("Gold", gold_change)) if value is None],
        "interpretation": "Broad dollar/metals co-movement is treated as liquidity-consistent, not as proof of causality.",
    }

    return evidence


@dataclass(frozen=True, slots=True)
class TransmissionStateSnapshot:
    transmission_id: str
    market: str
    window: str
    as_of: str
    response_divergence_id: str
    information_snapshot_id: str
    cross_market_snapshot_id: str
    response_status: str
    expected_direction: str
    realized_direction: str
    resolution_status: str
    dominant_channel: str | None
    confidence: float
    channel_scores: dict[str, float]
    evidence: dict[str, dict[str, Any]]
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.resolution_status not in {"RESOLVED", "UNRESOLVED"}:
            raise ValueError("resolution_status must be RESOLVED or UNRESOLVED")
        if self.dominant_channel is not None and self.dominant_channel not in CHANNELS:
            raise ValueError(f"unsupported dominant channel: {self.dominant_channel}")
        if set(self.channel_scores) != set(CHANNELS):
            raise ValueError("channel_scores must contain every TransmissionState channel")
        object.__setattr__(self, "channel_scores", dict(self.channel_scores))
        object.__setattr__(self, "evidence", {name: dict(value) for name, value in self.evidence.items()})

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "TransmissionStateSnapshot":
        return cls(**payload)


class TransmissionStateStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS transmission_state_snapshots (
                    transmission_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    window TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    response_divergence_id TEXT NOT NULL,
                    resolution_status TEXT NOT NULL,
                    dominant_channel TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_transmission_state_market_time
                ON transmission_state_snapshots(market, as_of);
                """
            )

    def save(self, snapshot: TransmissionStateSnapshot) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO transmission_state_snapshots(
                    transmission_id, market, window, as_of, response_divergence_id,
                    resolution_status, dominant_channel, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transmission_id) DO NOTHING
                """,
                (
                    snapshot.transmission_id,
                    snapshot.market,
                    snapshot.window,
                    snapshot.as_of,
                    snapshot.response_divergence_id,
                    snapshot.resolution_status,
                    snapshot.dominant_channel,
                    json.dumps(snapshot.to_record(), sort_keys=True),
                ),
            )

    def save_all(self, snapshots: tuple[TransmissionStateSnapshot, ...]) -> int:
        for snapshot in snapshots:
            self.save(snapshot)
        return len(snapshots)

    def load_latest(self, *, market: str = "Silver") -> TransmissionStateSnapshot | None:
        with connect(self.path) as db:
            row = db.execute(
                """
                SELECT payload_json FROM transmission_state_snapshots
                WHERE market=? ORDER BY as_of DESC LIMIT 1
                """,
                (market,),
            ).fetchone()
        return None if row is None else TransmissionStateSnapshot.from_record(json.loads(row["payload_json"]))


def build_transmission_state(divergence: ResponseDivergenceSnapshot) -> TransmissionStateSnapshot:
    """Classify descriptive cross-market patterns without claiming causality.

    A channel may resolve only when its signed score supports the realized Silver
    direction, exceeds the minimum evidence threshold, and clearly leads competing
    channels. Otherwise the observation is persisted as UNRESOLVED.
    """
    evidence = _channel_evidence(divergence)
    scores = {channel: float(evidence[channel]["score"]) for channel in CHANNELS}
    realized_sign = _direction_sign(divergence.realized_direction)

    candidates = sorted(
        (
            (channel, abs(score))
            for channel, score in scores.items()
            if realized_sign != 0 and _sign(score, dead_zone=0.0) == realized_sign
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    top_channel = candidates[0][0] if candidates else None
    top_score = candidates[0][1] if candidates else 0.0
    second_score = candidates[1][1] if len(candidates) > 1 else 0.0

    resolved = (
        divergence.status != "UNCONFIRMED"
        and top_channel is not None
        and top_score >= _RESOLUTION_THRESHOLD
        and (top_score - second_score) >= _RESOLUTION_MARGIN
    )
    resolution_status = "RESOLVED" if resolved else "UNRESOLVED"
    dominant = top_channel if resolved else None

    payload = {
        "response_divergence_id": divergence.divergence_id,
        "engine_version": ENGINE_VERSION,
    }
    return TransmissionStateSnapshot(
        transmission_id=_stable_id(payload),
        market=divergence.market,
        window=divergence.window,
        as_of=divergence.as_of,
        response_divergence_id=divergence.divergence_id,
        information_snapshot_id=divergence.information_snapshot_id,
        cross_market_snapshot_id=divergence.cross_market_snapshot_id,
        response_status=divergence.status,
        expected_direction=divergence.expected_direction,
        realized_direction=divergence.realized_direction,
        resolution_status=resolution_status,
        dominant_channel=dominant,
        confidence=round(top_score, 3),
        channel_scores={channel: round(scores[channel], 3) for channel in CHANNELS},
        evidence=evidence,
    )
