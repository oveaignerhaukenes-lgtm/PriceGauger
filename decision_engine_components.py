from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from analysis_view_preferences import ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL
from database import connect
from historical_signal_store import HistoricalRuntimeSignal
from state_contracts import DecisionStateSnapshot, MarketStateSnapshot


VALID_DECISION_DIRECTIONS = {"LONG_BIAS", "SHORT_BIAS", "NEUTRAL"}


@dataclass(frozen=True, slots=True)
class DecisionEngineComponents:
    decision_snapshot_id: str
    market: str
    as_of: str
    scores: dict[str, float]
    weights: dict[str, float]
    available_engines: tuple[str, ...]
    historical_assessment_id: str = ""

    def to_record(self) -> dict:
        record = asdict(self)
        record["available_engines"] = list(self.available_engines)
        return record


def _direction(score: float) -> str:
    return "LONG_BIAS" if score > 0.10 else "SHORT_BIAS" if score < -0.10 else "NEUTRAL"


def _information_score(decision: DecisionStateSnapshot, market_state: MarketStateSnapshot | None) -> tuple[float, float]:
    if market_state is None or market_state.component.freshness != "FRESH":
        return float(decision.direction_score), 0.0
    technical = float(market_state.direction_score)
    information = (float(decision.direction_score) - 0.28 * technical) / 0.72
    return max(-1.0, min(1.0, information)), technical


def apply_historical_confirmation(
    decision: DecisionStateSnapshot,
    *,
    market_state: MarketStateSnapshot | None,
    historical: HistoricalRuntimeSignal | None,
) -> tuple[DecisionStateSnapshot, DecisionEngineComponents]:
    """Blend an event-matched historical signal conservatively into Decision State.

    Without a historical signal this returns the original Decision State unchanged.
    Historical confirmation receives 15% of the final score; the existing
    information/technical blend retains 85%. Special stale/insufficient directions
    are never upgraded by historical data alone.
    """
    information, technical = _information_score(decision, market_state)
    technical_available = market_state is not None and market_state.component.freshness == "FRESH"
    base_weights = {
        ENGINE_NEWS_CONTEXT: 0.72 if technical_available else 1.0,
        ENGINE_TECHNICAL: 0.28 if technical_available else 0.0,
        ENGINE_HISTORICAL: 0.0,
    }
    scores = {
        ENGINE_NEWS_CONTEXT: information,
        ENGINE_TECHNICAL: technical,
        ENGINE_HISTORICAL: 0.0 if historical is None else float(historical.direction_score),
    }
    available = [ENGINE_NEWS_CONTEXT]
    if technical_available:
        available.append(ENGINE_TECHNICAL)

    adjusted = decision
    historical_id = ""
    weights = dict(base_weights)
    if historical is not None:
        historical_id = historical.assessment_id
        available.append(ENGINE_HISTORICAL)
        weights = {
            ENGINE_NEWS_CONTEXT: base_weights[ENGINE_NEWS_CONTEXT] * 0.85,
            ENGINE_TECHNICAL: base_weights[ENGINE_TECHNICAL] * 0.85,
            ENGINE_HISTORICAL: 0.15,
        }
        if decision.direction in VALID_DECISION_DIRECTIONS:
            score = max(-1.0, min(1.0, 0.85 * float(decision.direction_score) + 0.15 * float(historical.direction_score)))
            confidence = max(0.0, min(1.0, 0.90 * float(decision.confidence) + 0.10 * float(historical.confidence)))
            identity = f"{decision.snapshot_id}|{historical.assessment_id}|{score:.6f}"
            snapshot_id = "decision-state:" + sha256(identity.encode("utf-8")).hexdigest()[:24]
            adjusted = replace(
                decision,
                snapshot_id=snapshot_id,
                direction=_direction(score),
                direction_score=round(score, 4),
                confidence=confidence,
                status_reason=(
                    decision.status_reason
                    + f" Historical confirmation {historical.direction_score:+.2f} "
                    + f"from {historical.independent_analogues} analogue(s), weight 0.15."
                ),
            )

    components = DecisionEngineComponents(
        decision_snapshot_id=adjusted.snapshot_id,
        market=decision.market,
        as_of=decision.as_of,
        scores={key: round(float(value), 6) for key, value in scores.items()},
        weights={key: round(float(value), 6) for key, value in weights.items()},
        available_engines=tuple(available),
        historical_assessment_id=historical_id,
    )
    return adjusted, components


def projected_score(components: DecisionEngineComponents, enabled_engines: tuple[str, ...] | list[str]) -> float | None:
    enabled = set(str(item) for item in enabled_engines)
    active = [
        engine
        for engine in components.available_engines
        if engine in enabled and float(components.weights.get(engine, 0.0)) > 0.0
    ]
    if not active:
        return None
    total_weight = sum(float(components.weights[engine]) for engine in active)
    if total_weight <= 0:
        return None
    score = sum(float(components.scores[engine]) * float(components.weights[engine]) for engine in active) / total_weight
    return max(-1.0, min(1.0, score))


def projected_direction(score: float | None) -> str:
    return "NO_ENGINES" if score is None else _direction(float(score))


class DecisionEngineComponentStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS decision_engine_components (
                    decision_snapshot_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_decision_components_market_as_of
                ON decision_engine_components(market, as_of);
                """
            )

    def _connect(self):
        return connect(self.path)

    def save_all(self, items: list[DecisionEngineComponents]) -> int:
        with self._connect() as db:
            for item in items:
                db.execute(
                    """
                    INSERT INTO decision_engine_components(decision_snapshot_id, market, as_of, payload_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(decision_snapshot_id) DO UPDATE SET
                        market=excluded.market,
                        as_of=excluded.as_of,
                        payload_json=excluded.payload_json,
                        recorded_at=CURRENT_TIMESTAMP
                    """,
                    (item.decision_snapshot_id, item.market, item.as_of, json.dumps(item.to_record(), sort_keys=True)),
                )
        return len(items)

    def load_latest(self, *, market: str) -> DecisionEngineComponents | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM decision_engine_components
                WHERE market=?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (str(market),),
            ).fetchone()
        if row is None:
            return None
        record = json.loads(row["payload_json"])
        record["available_engines"] = tuple(record.get("available_engines") or ())
        return DecisionEngineComponents(**record)
