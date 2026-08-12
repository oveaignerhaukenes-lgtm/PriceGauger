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
SUPPORT_LEVELS = ("SUPPORTED", "PARTIAL", "CONFLICTING", "INSUFFICIENT")
_MARKET_DEAD_ZONE_PCT = 0.05
# Yield observations are expressed as percentage-point changes. This is only a
# measurement/noise gate, not an epistemic channel weight.
_YIELD_DEAD_ZONE_PCT = 0.01


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "transmission-state:" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _sign(value: float | None, *, dead_zone: float) -> int:
    if value is None:
        return 0
    if value > dead_zone:
        return 1
    if value < -dead_zone:
        return -1
    return 0


def _direction(sign: int) -> str:
    if sign > 0:
        return "UP"
    if sign < 0:
        return "DOWN"
    return "NEUTRAL"


def _direction_sign(direction: str) -> int:
    if direction == "UP":
        return 1
    if direction == "DOWN":
        return -1
    return 0


def _change(divergence: ResponseDivergenceSnapshot, name: str) -> float | None:
    item = divergence.supporting_observations.get(name)
    if not item or item.get("window_coverage") != "VALID":
        return None
    value = item.get("change")
    return None if value is None else float(value)


def _market_sign(divergence: ResponseDivergenceSnapshot, name: str) -> int:
    return _sign(_change(divergence, name), dead_zone=_MARKET_DEAD_ZONE_PCT)


def _yield_sign(divergence: ResponseDivergenceSnapshot, name: str) -> int:
    return _sign(_change(divergence, name), dead_zone=_YIELD_DEAD_ZONE_PCT)


def _evidence(
    *,
    support_level: str,
    pressure_sign: int = 0,
    signals: list[str] | None = None,
    missing_inputs: list[str] | None = None,
    interpretation: str,
) -> dict[str, Any]:
    if support_level not in SUPPORT_LEVELS:
        raise ValueError(f"unsupported support level: {support_level}")
    return {
        "support_level": support_level,
        "pressure_direction": _direction(pressure_sign),
        "signals": list(signals or ()),
        "missing_inputs": list(missing_inputs or ()),
        "interpretation": interpretation,
    }


def _rates_fx_evidence(divergence: ResponseDivergenceSnapshot) -> dict[str, Any]:
    dxy_change = _change(divergence, "DXY")
    dxy_sign = _market_sign(divergence, "DXY")
    # Stronger DXY implies downward Silver pressure; weaker DXY implies upward.
    dxy_pressure = -dxy_sign

    yield_names = ("US2Y", "US10Y", "US30Y")
    yield_changes = {name: _change(divergence, name) for name in yield_names}
    yield_pressures = {
        name: -_yield_sign(divergence, name) for name in yield_names
    }
    meaningful_yields = [value for value in yield_pressures.values() if value != 0]
    yield_conflict = len(set(meaningful_yields)) > 1
    yield_pressure = meaningful_yields[0] if meaningful_yields and not yield_conflict else 0

    signals: list[str] = []
    if dxy_change is not None:
        signals.append(f"DXY {dxy_change:+.3f}% over {divergence.window}")
    for name in yield_names:
        value = yield_changes[name]
        if value is not None:
            signals.append(f"{name} {value:+.4f} over {divergence.window}")
    missing = [name for name in ("DXY",) + yield_names if _change(divergence, name) is None]

    if yield_conflict or (dxy_pressure and yield_pressure and dxy_pressure != yield_pressure):
        return _evidence(
            support_level="CONFLICTING",
            signals=signals,
            missing_inputs=missing,
            interpretation="Available DXY/yield observations imply conflicting Silver pressure.",
        )
    if dxy_pressure and yield_pressure and dxy_pressure == yield_pressure:
        return _evidence(
            support_level="SUPPORTED",
            pressure_sign=dxy_pressure,
            signals=signals,
            missing_inputs=missing,
            interpretation="DXY and at least one Treasury yield tenor independently imply the same Silver pressure.",
        )
    if dxy_pressure or yield_pressure:
        return _evidence(
            support_level="PARTIAL",
            pressure_sign=dxy_pressure or yield_pressure,
            signals=signals,
            missing_inputs=missing,
            interpretation="Only one of the FX/rates evidence families provides directional confirmation.",
        )
    return _evidence(
        support_level="INSUFFICIENT",
        signals=signals,
        missing_inputs=missing,
        interpretation="No meaningful directional FX/rates evidence is available.",
    )


def _channel_evidence(divergence: ResponseDivergenceSnapshot) -> dict[str, dict[str, Any]]:
    silver_sign = _direction_sign(divergence.realized_direction)
    gold_change = _change(divergence, "Gold")
    brent_change = _change(divergence, "Brent")
    dxy_change = _change(divergence, "DXY")
    gold_sign = _market_sign(divergence, "Gold")
    brent_sign = _market_sign(divergence, "Brent")
    dxy_sign = _market_sign(divergence, "DXY")

    evidence: dict[str, dict[str, Any]] = {}

    # Gold is useful descriptive confirmation, but v1 has no independent safe-haven
    # basket. Therefore Gold alone can only provide PARTIAL evidence.
    evidence["SAFE_HAVEN"] = _evidence(
        support_level="PARTIAL" if gold_sign else "INSUFFICIENT",
        pressure_sign=gold_sign,
        signals=[] if gold_change is None else [f"Gold {gold_change:+.3f}% over {divergence.window}"],
        missing_inputs=[] if gold_change is not None else ["Gold"],
        interpretation="Gold supplies broad precious-metals confirmation only; v1 has no independent safe-haven basket.",
    )

    rates = _rates_fx_evidence(divergence)
    evidence["RATES_FX"] = rates

    # Energy-inflation requires both a meaningful Brent move and macro pressure in
    # the direction conventionally associated with that oil move. Missing yields do
    # not get replaced by numeric confidence penalties; they leave the mechanism
    # PARTIAL until the rates/FX family is itself SUPPORTED.
    energy_signals = [] if brent_change is None else [f"Brent {brent_change:+.3f}% over {divergence.window}"]
    energy_signals += list(rates["signals"])
    energy_missing = (["Brent"] if brent_change is None else []) + list(rates["missing_inputs"])
    rates_pressure = _direction_sign(str(rates["pressure_direction"]))
    energy_pressure = -1 if brent_sign > 0 else 1 if brent_sign < 0 else 0
    expected_macro_pressure = energy_pressure

    if brent_sign == 0:
        energy = _evidence(
            support_level="INSUFFICIENT",
            signals=energy_signals,
            missing_inputs=energy_missing,
            interpretation="No meaningful Brent move is available to identify an energy-inflation pattern.",
        )
    elif rates["support_level"] == "CONFLICTING" or (
        rates_pressure and rates_pressure != expected_macro_pressure
    ):
        energy = _evidence(
            support_level="CONFLICTING",
            signals=energy_signals,
            missing_inputs=energy_missing,
            interpretation="Brent and the available FX/rates observations imply conflicting transmission directions.",
        )
    elif rates["support_level"] == "SUPPORTED" and rates_pressure == expected_macro_pressure:
        energy = _evidence(
            support_level="SUPPORTED",
            pressure_sign=energy_pressure,
            signals=energy_signals,
            missing_inputs=energy_missing,
            interpretation="Brent and independently confirmed FX/rates pressure form a coherent energy-inflation pattern.",
        )
    else:
        energy = _evidence(
            support_level="PARTIAL",
            pressure_sign=energy_pressure,
            signals=energy_signals,
            missing_inputs=energy_missing,
            interpretation="Brent is consistent with an energy-inflation pattern, but FX/rates confirmation is incomplete.",
        )
    evidence["ENERGY_INFLATION"] = energy

    # Without a dedicated growth proxy, relative Gold/Silver behavior is only a
    # hypothesis flag and can never resolve this mechanism in v1.
    relative_metals = silver_sign != 0 and gold_sign != 0 and silver_sign != gold_sign
    evidence["INDUSTRIAL_GROWTH"] = _evidence(
        support_level="PARTIAL" if relative_metals else "INSUFFICIENT",
        pressure_sign=silver_sign if relative_metals else 0,
        signals=["Silver and Gold moved in opposite directions"] if relative_metals else [],
        missing_inputs=["dedicated_growth_proxy"],
        interpretation="Relative Gold/Silver behavior is hypothesis-level evidence only until a dedicated growth proxy exists.",
    )

    # Liquidity is represented as a discrete joint pattern, not a weighted blend.
    liquidity_signals: list[str] = []
    if dxy_change is not None:
        liquidity_signals.append(f"DXY {dxy_change:+.3f}% over {divergence.window}")
    if gold_change is not None:
        liquidity_signals.append(f"Gold {gold_change:+.3f}% over {divergence.window}")
    liquidity_missing = [name for name, value in (("DXY", dxy_change), ("Gold", gold_change)) if value is None]
    if silver_sign and gold_sign and dxy_sign and silver_sign == gold_sign == -dxy_sign:
        liquidity = _evidence(
            support_level="SUPPORTED",
            pressure_sign=silver_sign,
            signals=liquidity_signals,
            missing_inputs=liquidity_missing,
            interpretation="Silver and Gold moved together against DXY, consistent with a broad liquidity/dollar pattern.",
        )
    elif silver_sign and ((gold_sign and gold_sign == silver_sign) or (dxy_sign and -dxy_sign == silver_sign)):
        liquidity = _evidence(
            support_level="PARTIAL",
            pressure_sign=silver_sign,
            signals=liquidity_signals,
            missing_inputs=liquidity_missing,
            interpretation="Part of the broad dollar/metals liquidity pattern is present, but full joint confirmation is absent.",
        )
    elif silver_sign and gold_sign and dxy_sign:
        liquidity = _evidence(
            support_level="CONFLICTING",
            signals=liquidity_signals,
            missing_inputs=liquidity_missing,
            interpretation="DXY, Gold and Silver do not form a coherent broad liquidity pattern.",
        )
    else:
        liquidity = _evidence(
            support_level="INSUFFICIENT",
            signals=liquidity_signals,
            missing_inputs=liquidity_missing,
            interpretation="Insufficient joint DXY/Gold/Silver movement is available for a liquidity pattern.",
        )
    evidence["RISK_LIQUIDITY"] = liquidity

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
    support_levels: dict[str, str]
    evidence: dict[str, dict[str, Any]]
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION

    def __post_init__(self) -> None:
        if self.resolution_status not in {"RESOLVED", "UNRESOLVED"}:
            raise ValueError("resolution_status must be RESOLVED or UNRESOLVED")
        if self.dominant_channel is not None and self.dominant_channel not in CHANNELS:
            raise ValueError(f"unsupported dominant channel: {self.dominant_channel}")
        if set(self.support_levels) != set(CHANNELS):
            raise ValueError("support_levels must contain every TransmissionState channel")
        if any(level not in SUPPORT_LEVELS for level in self.support_levels.values()):
            raise ValueError("unsupported TransmissionState support level")
        object.__setattr__(self, "support_levels", dict(self.support_levels))
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
    """Describe mechanism support without assigning hand-written channel weights.

    A dominant channel is set only when exactly one mechanism has SUPPORTED evidence,
    its implied pressure matches the realized Silver direction, and the response is
    not UNCONFIRMED. Multiple supported stories remain explicitly UNRESOLVED.
    """
    evidence = _channel_evidence(divergence)
    support_levels = {channel: str(evidence[channel]["support_level"]) for channel in CHANNELS}
    realized_sign = _direction_sign(divergence.realized_direction)

    supported = [
        channel
        for channel in CHANNELS
        if support_levels[channel] == "SUPPORTED"
        and _direction_sign(str(evidence[channel]["pressure_direction"])) == realized_sign
    ]
    resolved = divergence.status != "UNCONFIRMED" and realized_sign != 0 and len(supported) == 1
    dominant = supported[0] if resolved else None

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
        resolution_status="RESOLVED" if resolved else "UNRESOLVED",
        dominant_channel=dominant,
        support_levels=support_levels,
        evidence=evidence,
    )
