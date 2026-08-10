from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from analysis_view_preferences import ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL
from state_contracts import MarketMoverAlert


SHOCK_PHASE_PRIOR_VERSION = "market-shock-phase-prior-v1"


@dataclass(frozen=True, slots=True)
class ShockPhasePrior:
    phase: str
    age_minutes: float | None
    multipliers: dict[str, float]
    version: str = SHOCK_PHASE_PRIOR_VERSION

    def multiplier(self, engine: str) -> float:
        return float(self.multipliers.get(str(engine), 1.0))


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def shock_phase_prior(
    alert: MarketMoverAlert | None,
    *,
    now: datetime | None = None,
) -> ShockPhasePrior:
    """Return an explicit market-structure prior after a material market mover.

    The prior encodes a deliberately simple starting assumption:
    - IMPACT: headline and technical response both matter immediately.
    - ABSORPTION: order flow / technical structure dominates while the shock is digested.
    - REBALANCE: technical influence decays as the market searches for a new consensus.
    - NORMALIZED: no phase multiplier; learned engine reliability carries the weights.

    These are priors, not learned truths. Later training recipes may replace the time
    boundaries and multipliers, but this version remains immutable for attribution.
    """
    if alert is None:
        return ShockPhasePrior(
            phase="NORMALIZED",
            age_minutes=None,
            multipliers={
                ENGINE_NEWS_CONTEXT: 1.0,
                ENGINE_TECHNICAL: 1.0,
                ENGINE_HISTORICAL: 1.0,
            },
        )

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_minutes = max(0.0, (current - _utc(alert.updated_at)).total_seconds() / 60.0)

    if age_minutes <= 15.0:
        phase = "IMPACT"
        multipliers = {
            ENGINE_NEWS_CONTEXT: 1.20,
            ENGINE_TECHNICAL: 1.15,
            ENGINE_HISTORICAL: 0.90,
        }
    elif age_minutes <= 120.0:
        phase = "ABSORPTION"
        multipliers = {
            ENGINE_NEWS_CONTEXT: 0.85,
            ENGINE_TECHNICAL: 1.35,
            ENGINE_HISTORICAL: 0.90,
        }
    elif age_minutes <= 480.0:
        phase = "REBALANCE"
        multipliers = {
            ENGINE_NEWS_CONTEXT: 1.00,
            ENGINE_TECHNICAL: 1.15,
            ENGINE_HISTORICAL: 1.00,
        }
    else:
        phase = "NORMALIZED"
        multipliers = {
            ENGINE_NEWS_CONTEXT: 1.0,
            ENGINE_TECHNICAL: 1.0,
            ENGINE_HISTORICAL: 1.0,
        }

    return ShockPhasePrior(
        phase=phase,
        age_minutes=round(age_minutes, 3),
        multipliers=multipliers,
    )
