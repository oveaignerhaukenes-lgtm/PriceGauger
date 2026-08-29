from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from autotrader_live_pilot_runtime_v2 import (
    LivePilotBindingV2,
    LivePilotEvaluationV2,
    LivePilotPlanningStateV2,
    _exact_observation_v2,
    _position_state_from_observation_v2,
    load_live_pilot_state_v2,
    persist_live_pilot_evaluation_v2,
    plan_live_pilot_step_v2,
    resolve_live_pilot_binding_v2,
)
from autotrader_macd_dry_run_v2 import closed_30m_bars_v2, macd_observations_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from saxo_provider import configured_client


DEFAULT_PILOT_SEED_CAPITAL = 500.0
DEFAULT_PILOT_CURRENCY = "NOK"


@dataclass(frozen=True, slots=True)
class PilotEquitySnapshotV2:
    """Settled strategy capital, isolated from the rest of the Saxo account.

    Only explicitly booked realized net P/L changes this ledger. Unrealized P/L,
    available account cash and unrelated deposits are deliberately excluded.
    """

    pilot_key: str
    currency: str
    seed_capital: float
    realized_net_pnl: float

    def __post_init__(self) -> None:
        if not self.pilot_key.strip():
            raise ValueError("pilot_key is required")
        if not self.currency.strip():
            raise ValueError("currency is required")
        if not math.isfinite(float(self.seed_capital)) or float(self.seed_capital) <= 0:
            raise ValueError("seed_capital must be finite and positive")
        if not math.isfinite(float(self.realized_net_pnl)):
            raise ValueError("realized_net_pnl must be finite")

    @property
    def equity(self) -> float:
        return float(self.seed_capital) + float(self.realized_net_pnl)

    @property
    def entry_budget(self) -> float:
        """Capital the next OPEN may use; never create exposure from negative equity."""
        return max(0.0, self.equity)


def pilot_equity_snapshot_v2(
    *,
    pilot_key: str,
    seed_capital: float,
    realized_net_pnl_entries: Iterable[float] = (),
    currency: str = DEFAULT_PILOT_CURRENCY,
) -> PilotEquitySnapshotV2:
    """Pure equity calculation used by persistence and unit tests."""
    realized = sum(float(item) for item in realized_net_pnl_entries)
    return PilotEquitySnapshotV2(
        pilot_key=str(pilot_key).strip(),
        currency=str(currency).strip().upper(),
        seed_capital=float(seed_capital),
        realized_net_pnl=realized,
    )


def initialize_pilot_equity_v2(
    *,
    pilot_key: str,
    seed_capital: float = DEFAULT_PILOT_SEED_CAPITAL,
    currency: str = DEFAULT_PILOT_CURRENCY,
) -> PilotEquitySnapshotV2:
    """Create the pilot capital boundary once and refuse silent later resets."""
    ensure_autotrader_schema_v2()
    key = str(pilot_key or "").strip()
    normalized_currency = str(currency or "").strip().upper()
    capital = float(seed_capital)
    if not key:
        raise ValueError("pilot_key is required")
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("seed_capital must be finite and positive")
    if not normalized_currency:
        raise ValueError("currency is required")

    with connect() as db:
        row = db.execute(
            """
            SELECT seed_capital, currency
            FROM pg_v2_autotrader_pilot_equity_state
            WHERE pilot_key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_pilot_equity_state
                    (pilot_key, seed_capital, currency)
                VALUES (?, ?, ?)
                """,
                (key, capital, normalized_currency),
            )
        else:
            existing_seed = float(row["seed_capital"] if isinstance(row, dict) else row[0])
            existing_currency = str(row["currency"] if isinstance(row, dict) else row[1])
            if abs(existing_seed - capital) > 1e-12:
                raise ValueError("pilot seed capital already exists with a different value")
            if existing_currency != normalized_currency:
                raise ValueError("pilot equity currency already exists with a different value")
    return load_pilot_equity_v2(pilot_key=key)


def load_pilot_equity_v2(*, pilot_key: str) -> PilotEquitySnapshotV2:
    ensure_autotrader_schema_v2()
    key = str(pilot_key or "").strip()
    if not key:
        raise ValueError("pilot_key is required")
    with connect() as db:
        row = db.execute(
            """
            SELECT state.seed_capital, state.currency,
                   COALESCE(SUM(events.realized_net_pnl), 0.0) AS realized_net_pnl
            FROM pg_v2_autotrader_pilot_equity_state AS state
            LEFT JOIN pg_v2_autotrader_pilot_equity_events AS events
              ON events.pilot_key = state.pilot_key
            WHERE state.pilot_key = ?
            GROUP BY state.pilot_key, state.seed_capital, state.currency
            """,
            (key,),
        ).fetchone()
    if row is None:
        raise LookupError(f"no pilot equity ledger for {key}")
    if isinstance(row, dict):
        seed = row["seed_capital"]
        currency = row["currency"]
        realized = row["realized_net_pnl"]
    else:
        seed, currency, realized = row
    return pilot_equity_snapshot_v2(
        pilot_key=key,
        seed_capital=float(seed),
        realized_net_pnl_entries=(float(realized),),
        currency=str(currency),
    )


def record_realized_net_pnl_v2(
    *,
    pilot_key: str,
    source_reference: str,
    realized_net_pnl: float,
    currency: str = DEFAULT_PILOT_CURRENCY,
    source_kind: str = "EXECUTION_RECONCILIATION",
) -> PilotEquitySnapshotV2:
    """Append one idempotent settled P/L event.

    `realized_net_pnl` must be net of transaction costs. The future execution
    adapter should call this only after a close is reconciled from an authoritative
    Saxo execution/fill source; observation-price estimates are not accepted here.
    """
    ensure_autotrader_schema_v2()
    key = str(pilot_key or "").strip()
    reference = str(source_reference or "").strip()
    normalized_currency = str(currency or "").strip().upper()
    normalized_kind = str(source_kind or "").strip().upper()
    amount = float(realized_net_pnl)
    if not key or not reference:
        raise ValueError("pilot_key and source_reference are required")
    if not normalized_currency or not normalized_kind:
        raise ValueError("currency and source_kind are required")
    if not math.isfinite(amount):
        raise ValueError("realized_net_pnl must be finite")

    current = load_pilot_equity_v2(pilot_key=key)
    if current.currency != normalized_currency:
        raise ValueError("realized P/L currency does not match pilot equity currency")

    event_id = str(uuid5(NAMESPACE_URL, f"pilot-equity|{key}|{normalized_kind}|{reference}"))
    with connect() as db:
        existing = db.execute(
            """
            SELECT realized_net_pnl, currency, source_kind, source_reference
            FROM pg_v2_autotrader_pilot_equity_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if existing is None:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_pilot_equity_events
                    (event_id, pilot_key, source_kind, source_reference,
                     realized_net_pnl, currency)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, key, normalized_kind, reference, amount, normalized_currency),
            )
        else:
            values = dict(existing) if isinstance(existing, dict) else {
                "realized_net_pnl": existing[0],
                "currency": existing[1],
                "source_kind": existing[2],
                "source_reference": existing[3],
            }
            if (
                abs(float(values["realized_net_pnl"]) - amount) > 1e-12
                or str(values["currency"]) != normalized_currency
                or str(values["source_kind"]) != normalized_kind
                or str(values["source_reference"]) != reference
            ):
                raise ValueError("pilot equity event identity was reused with different contents")
    return load_pilot_equity_v2(pilot_key=key)


def refresh_pending_reversal_budget_v2(
    *,
    state: LivePilotPlanningStateV2,
    equity: PilotEquitySnapshotV2,
) -> LivePilotPlanningStateV2:
    """Refresh pending reversal sizing from settled equity when capital is available.

    A reversal signal can be created while the old leg is still open. Once that leg
    closes, newly realized profit belongs to the pilot and may fund the opposite
    OPEN. If equity is exhausted we preserve the old intent so CLOSE remains
    plannable, but a later flat-state OPEN is blocked by `planning_budget_v2`.
    """
    if state.pending_intent is None or equity.entry_budget <= 0:
        return state
    refreshed = replace(
        state.pending_intent,
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
    )
    return replace(state, pending_intent=refreshed, reversal_pending=True)


def planning_budget_v2(
    *,
    equity: PilotEquitySnapshotV2,
    position_is_flat: bool,
) -> float:
    """Return a positive planner budget without letting exhaustion block CLOSE.

    The MACD intent contract requires a positive budget even for a CLOSE decision,
    though sizing is irrelevant to that risk-reducing action. When a position still
    exists, seed capital is therefore used only as a non-executing planner placeholder
    if settled equity is exhausted. Once FLAT, zero equity fails closed before OPEN.
    """
    if equity.entry_budget > 0:
        return equity.entry_budget
    if position_is_flat:
        raise ValueError("pilot equity is exhausted; no new exposure may be opened")
    return equity.seed_capital


def run_compounding_live_pilot_planning_once_v2(
    *,
    account_id: str,
    anchor_net_position_id: str,
    uic: int,
    asset_type: str,
    seed_capital: float = DEFAULT_PILOT_SEED_CAPITAL,
    currency: str = DEFAULT_PILOT_CURRENCY,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> LivePilotEvaluationV2:
    """Plan the live pilot using only its seed capital plus settled realized P/L."""
    ensure_autotrader_schema_v2()
    binding: LivePilotBindingV2 = resolve_live_pilot_binding_v2(
        account_id=account_id,
        anchor_net_position_id=anchor_net_position_id,
        uic=uic,
        asset_type=asset_type,
    )
    equity = initialize_pilot_equity_v2(
        pilot_key=binding.pilot_key,
        seed_capital=seed_capital,
        currency=currency,
    )
    state = refresh_pending_reversal_budget_v2(
        state=load_live_pilot_state_v2(binding),
        equity=equity,
    )

    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    end = end.astimezone(timezone.utc)
    start = end - timedelta(days=14)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=binding.instrument_id,
        start=start,
        end=end,
        limit=50000,
    )
    points = tuple(item.point for item in bars)
    if not points:
        raise ValueError("live pilot has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=binding.market_name)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("live pilot requires enough exact canonical 1m history for MACD 12/26/9")

    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    live_positions = _position_observations_v2(client)
    observed = _exact_observation_v2(binding, live_positions)
    if state.last_evaluated_bar_time is None and observed is not None:
        anchor = binding.anchor_net_position_id
        if anchor and observed.net_position_id != anchor:
            raise ValueError("initial live position does not match the requested anchor net-position identity")

    budget = planning_budget_v2(equity=equity, position_is_flat=observed is None)
    evaluation = plan_live_pilot_step_v2(
        binding=binding,
        state=state,
        observed_state=_position_state_from_observation_v2(observed),
        observed_net_position_id=None if observed is None else observed.net_position_id,
        previous=observations[-2],
        current=observations[-1],
        budget_amount=budget,
        budget_currency=equity.currency,
    )
    persist_live_pilot_evaluation_v2(evaluation)
    return evaluation


__all__ = [
    "DEFAULT_PILOT_CURRENCY",
    "DEFAULT_PILOT_SEED_CAPITAL",
    "PilotEquitySnapshotV2",
    "initialize_pilot_equity_v2",
    "load_pilot_equity_v2",
    "pilot_equity_snapshot_v2",
    "planning_budget_v2",
    "record_realized_net_pnl_v2",
    "refresh_pending_reversal_budget_v2",
    "run_compounding_live_pilot_planning_once_v2",
]
