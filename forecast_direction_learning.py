from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

from analysis_view_preferences import ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL
from database import connect
from decision_engine_components import DecisionEngineComponents
from state_contracts import DecisionStateSnapshot


DIRECTION_LEARNING_VERSION = "forecast-direction-learning-v1"
MIN_ENGINE_SAMPLES = 8
MAX_RECENT_OUTCOMES = 60
_SCORE_DEADBAND = 0.08
_REALIZED_DEADBAND_PCT = 0.03
_ENGINE_ORDER = (ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL, ENGINE_HISTORICAL)


@dataclass(frozen=True, slots=True)
class EngineDirectionReliability:
    engine: str
    sample_count: int
    hit_count: int
    posterior_hit_rate: float
    weight_multiplier: float


@dataclass(frozen=True, slots=True)
class DirectionLearningProfile:
    market: str
    horizon_hours: float
    engines: tuple[EngineDirectionReliability, ...]
    engine_version: str = DIRECTION_LEARNING_VERSION

    def multiplier(self, engine: str) -> float:
        for item in self.engines:
            if item.engine == engine:
                return item.weight_multiplier
        return 1.0


def _direction(value: float) -> str:
    return "LONG_BIAS" if value > 0.10 else "SHORT_BIAS" if value < -0.10 else "NEUTRAL"


def _load_training_rows(
    path: str | Path,
    *,
    market: str,
    horizon_hours: float,
    limit: int = MAX_RECENT_OUTCOMES,
) -> list[tuple[float, dict[str, float], dict[str, float]]]:
    """Return realized move plus frozen component scores/weights for completed forecasts."""
    with connect(path) as db:
        rows = db.execute(
            """
            SELECT o.payload_json AS outcome_json,
                   c.payload_json AS component_json
            FROM forecast_outcomes o
            JOIN forecast_snapshots f ON f.forecast_id=o.forecast_id
            JOIN decision_engine_components c ON c.decision_snapshot_id=f.decision_snapshot_id
            WHERE o.market=? AND o.status='COMPLETE'
            ORDER BY o.forecast_as_of DESC
            LIMIT ?
            """,
            (str(market), max(1, int(limit) * 4)),
        ).fetchall()

    result: list[tuple[float, dict[str, float], dict[str, float]]] = []
    for row in rows:
        outcome = json.loads(row["outcome_json"])
        observed_horizon = outcome.get("horizon_hours")
        realized = outcome.get("realized_move_pct")
        if observed_horizon is None or realized is None:
            continue
        if abs(float(observed_horizon) - float(horizon_hours)) > 1e-6:
            continue
        components = json.loads(row["component_json"])
        scores = {str(k): float(v) for k, v in (components.get("scores") or {}).items()}
        weights = {str(k): float(v) for k, v in (components.get("weights") or {}).items()}
        result.append((float(realized), scores, weights))
        if len(result) >= max(1, int(limit)):
            break
    return result


def build_direction_learning_profile(
    path: str | Path,
    *,
    market: str,
    horizon_hours: float,
    min_samples: int = MIN_ENGINE_SAMPLES,
    limit: int = MAX_RECENT_OUTCOMES,
) -> DirectionLearningProfile | None:
    rows = _load_training_rows(
        path,
        market=market,
        horizon_hours=horizon_hours,
        limit=limit,
    )
    reliabilities: list[EngineDirectionReliability] = []
    for engine in _ENGINE_ORDER:
        samples = 0
        hits = 0
        for realized, scores, weights in rows:
            score = float(scores.get(engine, 0.0))
            weight = float(weights.get(engine, 0.0))
            if weight <= 0.0 or abs(score) < _SCORE_DEADBAND or abs(realized) < _REALIZED_DEADBAND_PCT:
                continue
            samples += 1
            if score * realized > 0.0:
                hits += 1
        if samples < max(1, int(min_samples)):
            continue

        # Beta(4,4) prior keeps small samples near 50/50. A 50% engine retains
        # multiplier 1.0; sustained success/failure changes influence gradually.
        posterior = (hits + 4.0) / (samples + 8.0)
        multiplier = 1.0 + 1.2 * (posterior - 0.5)
        multiplier = max(0.70, min(1.30, multiplier))
        reliabilities.append(
            EngineDirectionReliability(
                engine=engine,
                sample_count=samples,
                hit_count=hits,
                posterior_hit_rate=round(posterior, 6),
                weight_multiplier=round(multiplier, 6),
            )
        )

    if not reliabilities:
        return None
    return DirectionLearningProfile(
        market=str(market),
        horizon_hours=float(horizon_hours),
        engines=tuple(reliabilities),
    )


def apply_direction_learning(
    decision: DecisionStateSnapshot,
    components: DecisionEngineComponents,
    profile: DirectionLearningProfile | None,
) -> tuple[DecisionStateSnapshot, DecisionEngineComponents]:
    """Reweight frozen engine scores using only prior realized directional accuracy."""
    if profile is None or decision.direction not in {"LONG_BIAS", "SHORT_BIAS", "NEUTRAL"}:
        return decision, components

    adjusted_weights: dict[str, float] = {}
    for engine, weight in components.weights.items():
        adjusted_weights[engine] = max(0.0, float(weight)) * profile.multiplier(engine)
    total = sum(adjusted_weights.values())
    if total <= 0.0:
        return decision, components
    normalized = {engine: value / total for engine, value in adjusted_weights.items()}
    score = sum(float(components.scores.get(engine, 0.0)) * weight for engine, weight in normalized.items())
    score = max(-1.0, min(1.0, score))

    identity = (
        f"{decision.snapshot_id}|{profile.engine_version}|{profile.horizon_hours:.6f}|"
        + "|".join(f"{key}:{normalized[key]:.6f}" for key in sorted(normalized))
    )
    snapshot_id = "decision-state:" + sha256(identity.encode("utf-8")).hexdigest()[:24]
    reliability_text = ", ".join(
        f"{item.engine} {item.posterior_hit_rate:.0%}/{item.sample_count}"
        for item in profile.engines
    )
    adjusted_decision = replace(
        decision,
        snapshot_id=snapshot_id,
        direction=_direction(score),
        direction_score=round(score, 4),
        status_reason=(
            decision.status_reason
            + f" Learned engine direction weights ({profile.engine_version}): {reliability_text}."
        ),
    )
    adjusted_components = replace(
        components,
        decision_snapshot_id=snapshot_id,
        weights={key: round(value, 6) for key, value in normalized.items()},
    )
    return adjusted_decision, adjusted_components
