from __future__ import annotations

"""Read-only TradingDesk AutoManage state.

This module deliberately owns no execution transitions. It preserves the persisted
P/L pilot selection semantics formerly buried in the legacy Streamlit panel.
"""

from dataclasses import dataclass

from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
    load_strategy_enrollment_v2,
)
from database import connect
from trading_desk_v2_context import TradingDeskV2Context


@dataclass(frozen=True, slots=True)
class AutoManagePanelSnapshotV2:
    observation: PositionObservationV2
    enrollment: StrategyEnrollmentV2 | None
    pilot_key: str
    currency: str
    equity: float | None
    realized_net_pnl: float | None
    realized_events: int
    last_action: str | None
    last_outcome: str | None
    last_signal: str | None
    last_signal_at: str | None


def pnl_enrollments_for_context_v2(
    context: TradingDeskV2Context,
) -> tuple[tuple[StrategyEnrollmentV2, ...], bool]:
    """Prefer active pilots; otherwise expose latest LIVE pilot as read-only history."""
    active = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if int(item.market_id) == int(context.market_id)
    )
    if active:
        return active, False

    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE market_id = ? AND execution_mode = ?
            ORDER BY updated_at DESC, enrolled_at DESC
            LIMIT 1
            """,
            (int(context.market_id), EXECUTION_MODE_LIVE),
        ).fetchone()
    if row is None:
        return (), False
    pilot_key = str(dict(row)["pilot_key"] if isinstance(row, dict) else row[0])
    latest = load_strategy_enrollment_v2(pilot_key)
    return ((latest,) if latest is not None else ()), True


__all__ = ["AutoManagePanelSnapshotV2", "pnl_enrollments_for_context_v2"]
