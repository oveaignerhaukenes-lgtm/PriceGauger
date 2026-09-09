from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from autotrader_pilot_equity_v2 import PilotEquitySnapshotV2, load_pilot_equity_v2
from database import connect


@dataclass(frozen=True, slots=True)
class PilotStatusV1:
    pilot_key: str
    currency: str
    seed_capital: float
    realized_net_pnl: float
    equity: float
    closed_trades: int
    wins: int
    losses: int
    breakeven: int
    last_open_amount: float | None
    last_open_budget: float | None
    last_open_initial_margin: float | None
    last_open_notional: float | None
    last_open_status: str | None
    last_open_at: datetime | None

    @property
    def return_pct(self) -> float:
        if self.seed_capital <= 0:
            return 0.0
        return (self.realized_net_pnl / self.seed_capital) * 100.0

    @property
    def win_rate_pct(self) -> float | None:
        resolved = self.wins + self.losses
        if resolved <= 0:
            return None
        return (self.wins / resolved) * 100.0

    @property
    def harvest_threshold(self) -> float:
        """Future harvesting starts only after the pilot has doubled its seed."""
        return self.seed_capital * 2.0

    @property
    def capital_utilization_pct(self) -> float | None:
        if self.last_open_initial_margin is None or self.last_open_budget is None:
            return None
        if self.last_open_budget <= 0:
            return None
        return (self.last_open_initial_margin / self.last_open_budget) * 100.0


def _row_value(row: Any, name: str, index: int, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        return row[index]
    except (IndexError, TypeError):
        return default


def _trade_counts_v1(pilot_key: str) -> tuple[int, int, int, int]:
    with connect() as db:
        row = db.execute(
            """
            SELECT COUNT(*) AS closed_trades,
                   COALESCE(SUM(CASE WHEN realized_net_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(CASE WHEN realized_net_pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
                   COALESCE(SUM(CASE WHEN realized_net_pnl = 0 THEN 1 ELSE 0 END), 0) AS breakeven
            FROM pg_v2_autotrader_pilot_equity_events
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    return (
        int(_row_value(row, "closed_trades", 0, 0) or 0),
        int(_row_value(row, "wins", 1, 0) or 0),
        int(_row_value(row, "losses", 2, 0) or 0),
        int(_row_value(row, "breakeven", 3, 0) or 0),
    )


def _latest_open_v1(pilot_key: str) -> tuple[float | None, float | None, float | None, float | None, str | None, datetime | None]:
    with connect() as db:
        row = db.execute(
            """
            SELECT attempt.amount,
                   attempt.budget_amount,
                   attempt.precheck_initial_margin,
                   attempt.precheck_notional,
                   attempt.status,
                   attempt.updated_at
            FROM pg_v2_autotrader_live_open_attempts AS attempt
            JOIN pg_v2_autotrader_execution_requests AS request
              ON request.request_id = attempt.request_id
            WHERE request.pilot_key = ?
            ORDER BY attempt.updated_at DESC
            LIMIT 1
            """,
            (str(pilot_key),),
        ).fetchone()
    if row is None:
        return None, None, None, None, None, None
    return (
        None if _row_value(row, "amount", 0) is None else float(_row_value(row, "amount", 0)),
        None if _row_value(row, "budget_amount", 1) is None else float(_row_value(row, "budget_amount", 1)),
        None if _row_value(row, "precheck_initial_margin", 2) is None else float(_row_value(row, "precheck_initial_margin", 2)),
        None if _row_value(row, "precheck_notional", 3) is None else float(_row_value(row, "precheck_notional", 3)),
        None if _row_value(row, "status", 4) is None else str(_row_value(row, "status", 4)),
        _row_value(row, "updated_at", 5),
    )


def pilot_status_from_snapshot_v1(
    snapshot: PilotEquitySnapshotV2,
    *,
    closed_trades: int,
    wins: int,
    losses: int,
    breakeven: int,
    last_open_amount: float | None = None,
    last_open_budget: float | None = None,
    last_open_initial_margin: float | None = None,
    last_open_notional: float | None = None,
    last_open_status: str | None = None,
    last_open_at: datetime | None = None,
) -> PilotStatusV1:
    return PilotStatusV1(
        pilot_key=snapshot.pilot_key,
        currency=snapshot.currency,
        seed_capital=float(snapshot.seed_capital),
        realized_net_pnl=float(snapshot.realized_net_pnl),
        equity=float(snapshot.equity),
        closed_trades=max(0, int(closed_trades)),
        wins=max(0, int(wins)),
        losses=max(0, int(losses)),
        breakeven=max(0, int(breakeven)),
        last_open_amount=last_open_amount,
        last_open_budget=last_open_budget,
        last_open_initial_margin=last_open_initial_margin,
        last_open_notional=last_open_notional,
        last_open_status=last_open_status,
        last_open_at=last_open_at,
    )


def load_pilot_status_v1(pilot_key: str) -> PilotStatusV1:
    snapshot = load_pilot_equity_v2(pilot_key=str(pilot_key))
    closed_trades, wins, losses, breakeven = _trade_counts_v1(snapshot.pilot_key)
    amount, budget, margin, notional, status, updated_at = _latest_open_v1(snapshot.pilot_key)
    return pilot_status_from_snapshot_v1(
        snapshot,
        closed_trades=closed_trades,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        last_open_amount=amount,
        last_open_budget=budget,
        last_open_initial_margin=margin,
        last_open_notional=notional,
        last_open_status=status,
        last_open_at=updated_at,
    )


__all__ = [
    "PilotStatusV1",
    "load_pilot_status_v1",
    "pilot_status_from_snapshot_v1",
]
