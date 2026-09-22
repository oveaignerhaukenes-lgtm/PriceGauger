from __future__ import annotations

from dataclasses import dataclass

from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from autotrader_v3_domain import DecisionSnapshotV3
from autotrader_v3_read_model_v1 import observe_v2_as_v3_v1


@dataclass(frozen=True, slots=True)
class TraderFleetRowV3:
    snapshot: DecisionSnapshotV3
    enabled: bool
    execution_mode: str

    @property
    def truth_line(self) -> str:
        snap = self.snapshot
        return (
            f"{snap.strategy_key} · kapital {snap.capital_allocation.tradeable_pct:.0f}% · "
            f"base {snap.base_target.amount:+.2f} → effektiv {snap.effective_target.amount:+.2f} → "
            f"risk {snap.risk_approved_target.amount:+.2f} · "
            f"Saxo {snap.actual_inventory.amount:+.2f} · pending {snap.pending_delta:+.2f}"
        )


def build_fleet_read_model_v3(
    enrollments: tuple[StrategyEnrollmentV2, ...],
    observations: tuple[PositionObservationV2, ...],
) -> tuple[TraderFleetRowV3, ...]:
    """Project current v2 traders into the v3 fleet model without authority."""
    rows: list[TraderFleetRowV3] = []
    seen_boundaries: set[tuple[str, int, str]] = set()
    for enrollment in enrollments:
        boundary = (enrollment.account_id, int(enrollment.uic), enrollment.asset_type)
        if boundary in seen_boundaries:
            # During migration several historical strategy enrollments can point at the
            # same product. A v3 fleet row is an account/product trader, not a strategy
            # history row; prefer the first enabled enrollment supplied by the caller.
            continue
        seen_boundaries.add(boundary)
        snap = observe_v2_as_v3_v1(enrollment, observations)
        rows.append(
            TraderFleetRowV3(
                snapshot=snap,
                enabled=bool(enrollment.enabled),
                execution_mode=str(enrollment.execution_mode),
            )
        )
    return tuple(rows)


__all__ = ["TraderFleetRowV3", "build_fleet_read_model_v3"]
