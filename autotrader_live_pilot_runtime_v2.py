from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from autotrader_macd_dry_run_v2 import MacdObservationV2, closed_30m_bars_v2, macd_observations_v2
from autotrader_macd_flip_policy_v2 import (
    MACD_FLIP_STRATEGY_V2,
    MacdFlipIntentV2,
    macd_flip_intent_from_pair_v2,
    plan_macd_flip_action_v2,
)
from autotrader_position_controller_v2 import (
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionDecisionV2,
    PositionStateV2,
)
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from instrument_registry_v2 import resolve_instrument_source_v2
from saxo_provider import configured_client


PILOT_RECIPE_V2 = "autotrader-live-pilot-planning-v2.1"


@dataclass(frozen=True, slots=True)
class LivePilotBindingV2:
    """Exact Saxo product identity bound to one canonical v2 history source."""

    account_id: str
    anchor_net_position_id: str
    uic: int
    asset_type: str
    market_id: int
    market_name: str
    instrument_id: int

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id is required")
        if int(self.uic) <= 0:
            raise ValueError("uic must be positive")
        if not self.asset_type.strip():
            raise ValueError("asset_type is required")
        if int(self.market_id) <= 0 or int(self.instrument_id) <= 0:
            raise ValueError("canonical market_id/instrument_id are required")
        if not self.market_name.strip():
            raise ValueError("market_name is required")

    @property
    def pilot_key(self) -> str:
        return str(
            uuid5(
                NAMESPACE_URL,
                f"{MACD_FLIP_STRATEGY_V2}|{self.account_id}|{self.uic}|{self.asset_type}",
            )
        )

    @property
    def source_fingerprint(self) -> str:
        return "|".join(
            (
                "saxo",
                str(self.uic),
                self.asset_type,
                str(self.instrument_id),
                str(self.market_id),
                self.market_name,
            )
        )


@dataclass(frozen=True, slots=True)
class LivePilotPlanningStateV2:
    last_evaluated_bar_time: datetime | None = None
    reversal_pending: bool = False
    pending_intent: MacdFlipIntentV2 | None = None

    def __post_init__(self) -> None:
        if self.last_evaluated_bar_time is not None and self.last_evaluated_bar_time.tzinfo is None:
            raise ValueError("last_evaluated_bar_time must be timezone-aware")
        if bool(self.reversal_pending) != (self.pending_intent is not None):
            raise ValueError("reversal_pending and pending_intent must be set together")


@dataclass(frozen=True, slots=True)
class LivePilotEvaluationV2:
    evaluation_id: str
    binding: LivePilotBindingV2
    latest_closed_bar_time: datetime
    observed_net_position_id: str | None
    observed_state: PositionStateV2
    outcome_reason: str
    intent: MacdFlipIntentV2 | None
    decision: PositionDecisionV2 | None
    next_state: LivePilotPlanningStateV2


def resolve_live_pilot_binding_v2(
    *,
    account_id: str,
    anchor_net_position_id: str,
    uic: int,
    asset_type: str,
) -> LivePilotBindingV2:
    """Resolve exact UIC + AssetType through the canonical subscribed Saxo registry."""
    normalized_asset_type = str(asset_type or "").strip()
    source = resolve_instrument_source_v2(
        provider="saxo",
        provider_instrument_id=str(int(uic)),
        require_subscription=True,
    )
    resolved_asset_type = str(source.asset_type or "").strip()
    if not resolved_asset_type or resolved_asset_type != normalized_asset_type:
        raise ValueError(
            "Saxo UIC resolved to a different canonical AssetType; refusing ambiguous pilot binding"
        )
    return LivePilotBindingV2(
        account_id=str(account_id).strip(),
        anchor_net_position_id=str(anchor_net_position_id or "").strip(),
        uic=int(uic),
        asset_type=normalized_asset_type,
        market_id=int(source.market_id),
        market_name=source.market_name,
        instrument_id=int(source.instrument_id),
    )


def _position_state_from_observation_v2(
    observation: PositionObservationV2 | None,
) -> PositionStateV2:
    """Map the binary first pilot into the generic lifecycle controller.

    The pilot has no pyramiding or fractional rebalancing. One exact live product
    position is therefore the pilot's full current exposure. Margin/notional sizing
    remains downstream and is never inferred here.
    """
    if observation is None:
        return PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0)
    side = observation.direction.strip().lower()
    if side == "buy":
        direction = DIRECTION_LONG
    elif side == "sell":
        direction = DIRECTION_SHORT
    else:
        raise ValueError(f"unsupported Saxo position direction: {observation.direction}")
    return PositionStateV2(direction=direction, deployed_fraction=1.0)


def _fresh_cross_intent_v2(
    *,
    binding: LivePilotBindingV2,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    budget_amount: float,
    budget_currency: str,
) -> MacdFlipIntentV2 | None:
    return macd_flip_intent_from_pair_v2(
        market_id=binding.market_id,
        market_name=binding.market_name,
        previous=previous,
        current=current,
        target_fraction=1.0,
        budget_amount=float(budget_amount),
        budget_currency=budget_currency,
    )


def plan_live_pilot_step_v2(
    *,
    binding: LivePilotBindingV2,
    state: LivePilotPlanningStateV2,
    observed_state: PositionStateV2,
    observed_net_position_id: str | None,
    previous: MacdObservationV2,
    current: MacdObservationV2,
    budget_amount: float,
    budget_currency: str = "NOK",
) -> LivePilotEvaluationV2:
    """Plan one lifecycle step from the latest fully closed 30m MACD pair.

    The first observation bootstraps without replaying an old cross. Thereafter a
    new cross may create an entry/reversal intent. Only an intent that actually
    initiated an opposite-side CLOSE may persist across cycles to complete
    CLOSE -> observed FLAT -> OPEN. A separate hard stop therefore cannot reopen
    from a stale strategy signal.
    """
    if float(budget_amount) <= 0:
        raise ValueError("budget_amount must be positive")
    if not str(budget_currency).strip():
        raise ValueError("budget_currency is required")
    if previous.bar_time >= current.bar_time:
        raise ValueError("MACD observation pair must be strictly ordered")

    prior_bar = state.last_evaluated_bar_time
    pending = state.pending_intent
    intent: MacdFlipIntentV2 | None = None
    decision: PositionDecisionV2 | None = None
    outcome = "NO_NEW_CROSS"

    if prior_bar is None:
        pending = None
        outcome = "BOOTSTRAP_NO_REPLAY"
    else:
        fresh_intent = None
        if current.bar_time > prior_bar:
            fresh_intent = _fresh_cross_intent_v2(
                binding=binding,
                previous=previous,
                current=current,
                budget_amount=budget_amount,
                budget_currency=budget_currency,
            )

        if fresh_intent is not None:
            intent = fresh_intent
            decision = plan_macd_flip_action_v2(current=observed_state, intent=intent)
            outcome = "FRESH_MACD_CROSS"
            if (
                decision.action == "CLOSE"
                and decision.prior_direction != decision.desired_direction
                and decision.desired_direction in {DIRECTION_LONG, DIRECTION_SHORT}
            ):
                pending = intent
            else:
                # Any fresh cross supersedes an older reversal. Only a CLOSE-origin
                # reversal is allowed to carry its signal into a later flat cycle.
                pending = None
        elif pending is not None:
            # A pending reversal remains actionable even when a newer closed bar has
            # no cross. Do not insert a one-cycle gap just because the MACD bar moved.
            intent = pending
            decision = plan_macd_flip_action_v2(current=observed_state, intent=pending)
            if (
                observed_state.direction == pending.target_direction
                and observed_state.deployed_fraction > 1e-12
            ):
                pending = None
                outcome = "REVERSAL_TARGET_OBSERVED"
            else:
                outcome = "REVERSAL_PENDING"

    latest = current.bar_time if prior_bar is None or current.bar_time > prior_bar else prior_bar
    next_state = LivePilotPlanningStateV2(
        last_evaluated_bar_time=latest,
        reversal_pending=pending is not None,
        pending_intent=pending,
    )
    identity = "|".join(
        (
            PILOT_RECIPE_V2,
            binding.pilot_key,
            current.bar_time.isoformat(),
            observed_net_position_id or "FLAT",
            observed_state.direction,
            intent.event_id if intent is not None else "NO_INTENT",
            decision.action if decision is not None else "NO_ACTION",
            outcome,
            "PENDING" if next_state.reversal_pending else "SETTLED",
        )
    )
    return LivePilotEvaluationV2(
        evaluation_id=str(uuid5(NAMESPACE_URL, identity)),
        binding=binding,
        latest_closed_bar_time=current.bar_time,
        observed_net_position_id=observed_net_position_id,
        observed_state=observed_state,
        outcome_reason=outcome,
        intent=intent,
        decision=decision,
        next_state=next_state,
    )


def _row_value(row, key: str, index: int):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _utc(value) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_live_pilot_state_v2(binding: LivePilotBindingV2) -> LivePilotPlanningStateV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT strategy_key, account_id, net_position_id, uic, asset_type,
                   market_id, instrument_id, market_name, last_evaluated_bar_time,
                   reversal_pending, pending_intent_id, pending_signal_at,
                   pending_signal, pending_target_direction,
                   pending_previous_macd, pending_previous_signal,
                   pending_current_macd, pending_current_signal,
                   pending_target_fraction, pending_budget_amount, pending_budget_currency
            FROM pg_v2_autotrader_live_pilot_state
            WHERE pilot_key = ?
            """,
            (binding.pilot_key,),
        ).fetchone()
    if row is None:
        return LivePilotPlanningStateV2()

    expected = (
        ("strategy_key", MACD_FLIP_STRATEGY_V2, str(_row_value(row, "strategy_key", 0))),
        ("account_id", binding.account_id, str(_row_value(row, "account_id", 1))),
        ("uic", str(binding.uic), str(_row_value(row, "uic", 3))),
        ("asset_type", binding.asset_type, str(_row_value(row, "asset_type", 4))),
        ("market_id", str(binding.market_id), str(_row_value(row, "market_id", 5))),
        ("instrument_id", str(binding.instrument_id), str(_row_value(row, "instrument_id", 6))),
        ("market_name", binding.market_name, str(_row_value(row, "market_name", 7))),
    )
    mismatches = [name for name, wanted, actual in expected if wanted != actual]
    if mismatches:
        raise ValueError("persisted live pilot binding mismatch: " + ", ".join(mismatches))

    pending_id = _row_value(row, "pending_intent_id", 10)
    pending = None
    if pending_id is not None:
        signal_at = _utc(_row_value(row, "pending_signal_at", 11))
        if signal_at is None:
            raise ValueError("persisted pending pilot intent is missing signal_at")
        pending = MacdFlipIntentV2(
            event_id=str(pending_id),
            market_id=binding.market_id,
            market_name=binding.market_name,
            signal_at=signal_at,
            signal=str(_row_value(row, "pending_signal", 12)),
            target_direction=str(_row_value(row, "pending_target_direction", 13)),
            previous_macd=float(_row_value(row, "pending_previous_macd", 14)),
            previous_signal=float(_row_value(row, "pending_previous_signal", 15)),
            current_macd=float(_row_value(row, "pending_current_macd", 16)),
            current_signal=float(_row_value(row, "pending_current_signal", 17)),
            target_fraction=float(_row_value(row, "pending_target_fraction", 18)),
            budget_amount=float(_row_value(row, "pending_budget_amount", 19)),
            budget_currency=str(_row_value(row, "pending_budget_currency", 20)),
        )
    return LivePilotPlanningStateV2(
        last_evaluated_bar_time=_utc(_row_value(row, "last_evaluated_bar_time", 8)),
        reversal_pending=bool(_row_value(row, "reversal_pending", 9)),
        pending_intent=pending,
    )


def persist_live_pilot_evaluation_v2(evaluation: LivePilotEvaluationV2) -> None:
    binding = evaluation.binding
    state = evaluation.next_state
    pending = state.pending_intent
    intent = evaluation.intent
    decision = evaluation.decision
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_live_pilot_evaluations(
                evaluation_id, pilot_key, strategy_key, account_id, net_position_id,
                uic, asset_type, market_id, instrument_id, market_name,
                canonical_source_fingerprint, latest_closed_bar_time,
                observed_direction, observed_fraction, outcome_reason,
                intent_id, signal_at, signal, target_direction,
                previous_macd, previous_signal, current_macd, current_signal,
                requested_action, prior_direction, desired_direction,
                prior_fraction, target_fraction, delta_fraction, decision_rationale,
                reversal_pending
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evaluation_id) DO NOTHING
            """,
            (
                evaluation.evaluation_id,
                binding.pilot_key,
                MACD_FLIP_STRATEGY_V2,
                binding.account_id,
                evaluation.observed_net_position_id or binding.anchor_net_position_id,
                binding.uic,
                binding.asset_type,
                binding.market_id,
                binding.instrument_id,
                binding.market_name,
                binding.source_fingerprint,
                evaluation.latest_closed_bar_time,
                evaluation.observed_state.direction,
                evaluation.observed_state.deployed_fraction,
                evaluation.outcome_reason,
                None if intent is None else intent.event_id,
                None if intent is None else intent.signal_at,
                None if intent is None else intent.signal,
                None if intent is None else intent.target_direction,
                None if intent is None else intent.previous_macd,
                None if intent is None else intent.previous_signal,
                None if intent is None else intent.current_macd,
                None if intent is None else intent.current_signal,
                None if decision is None else decision.action,
                None if decision is None else decision.prior_direction,
                None if decision is None else decision.desired_direction,
                None if decision is None else decision.prior_fraction,
                None if decision is None else decision.target_fraction,
                None if decision is None else decision.delta_fraction,
                None if decision is None else decision.rationale,
                state.reversal_pending,
            ),
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_live_pilot_state(
                pilot_key, strategy_key, account_id, net_position_id, uic, asset_type,
                market_id, instrument_id, market_name, last_evaluated_bar_time,
                reversal_pending, pending_intent_id, pending_signal_at, pending_signal,
                pending_target_direction, pending_previous_macd, pending_previous_signal,
                pending_current_macd, pending_current_signal, pending_target_fraction,
                pending_budget_amount, pending_budget_currency, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                account_id=EXCLUDED.account_id,
                net_position_id=EXCLUDED.net_position_id,
                uic=EXCLUDED.uic,
                asset_type=EXCLUDED.asset_type,
                market_id=EXCLUDED.market_id,
                instrument_id=EXCLUDED.instrument_id,
                market_name=EXCLUDED.market_name,
                last_evaluated_bar_time=EXCLUDED.last_evaluated_bar_time,
                reversal_pending=EXCLUDED.reversal_pending,
                pending_intent_id=EXCLUDED.pending_intent_id,
                pending_signal_at=EXCLUDED.pending_signal_at,
                pending_signal=EXCLUDED.pending_signal,
                pending_target_direction=EXCLUDED.pending_target_direction,
                pending_previous_macd=EXCLUDED.pending_previous_macd,
                pending_previous_signal=EXCLUDED.pending_previous_signal,
                pending_current_macd=EXCLUDED.pending_current_macd,
                pending_current_signal=EXCLUDED.pending_current_signal,
                pending_target_fraction=EXCLUDED.pending_target_fraction,
                pending_budget_amount=EXCLUDED.pending_budget_amount,
                pending_budget_currency=EXCLUDED.pending_budget_currency,
                updated_at=now()
            """,
            (
                binding.pilot_key,
                MACD_FLIP_STRATEGY_V2,
                binding.account_id,
                binding.anchor_net_position_id,
                binding.uic,
                binding.asset_type,
                binding.market_id,
                binding.instrument_id,
                binding.market_name,
                state.last_evaluated_bar_time,
                state.reversal_pending,
                None if pending is None else pending.event_id,
                None if pending is None else pending.signal_at,
                None if pending is None else pending.signal,
                None if pending is None else pending.target_direction,
                None if pending is None else pending.previous_macd,
                None if pending is None else pending.previous_signal,
                None if pending is None else pending.current_macd,
                None if pending is None else pending.current_signal,
                None if pending is None else pending.target_fraction,
                None if pending is None else pending.budget_amount,
                None if pending is None else pending.budget_currency,
            ),
        )


def _exact_observation_v2(
    binding: LivePilotBindingV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == binding.account_id
        and int(item.uic) == binding.uic
        and item.asset_type == binding.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("multiple live Saxo net positions match the exact pilot product identity")
    return matches[0] if matches else None


def run_live_pilot_planning_once_v2(
    *,
    account_id: str,
    anchor_net_position_id: str,
    uic: int,
    asset_type: str,
    budget_amount: float,
    budget_currency: str = "NOK",
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> LivePilotEvaluationV2:
    """Read live Saxo state + exact canonical history and persist a plan only."""
    ensure_autotrader_schema_v2()
    binding = resolve_live_pilot_binding_v2(
        account_id=account_id,
        anchor_net_position_id=anchor_net_position_id,
        uic=uic,
        asset_type=asset_type,
    )
    state = load_live_pilot_state_v2(binding)

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

    # Reuse the proven read-only Saxo net-position parser. This performs GET only;
    # this runtime intentionally imports no execution/order adapter.
    live_positions = _position_observations_v2(configured_client())
    observed = _exact_observation_v2(binding, live_positions)
    if state.last_evaluated_bar_time is None and observed is not None:
        anchor = binding.anchor_net_position_id
        if anchor and observed.net_position_id != anchor:
            raise ValueError("initial live position does not match the requested anchor net-position identity")

    evaluation = plan_live_pilot_step_v2(
        binding=binding,
        state=state,
        observed_state=_position_state_from_observation_v2(observed),
        observed_net_position_id=None if observed is None else observed.net_position_id,
        previous=observations[-2],
        current=observations[-1],
        budget_amount=budget_amount,
        budget_currency=budget_currency,
    )
    persist_live_pilot_evaluation_v2(evaluation)
    return evaluation


__all__ = [
    "LivePilotBindingV2",
    "LivePilotEvaluationV2",
    "LivePilotPlanningStateV2",
    "PILOT_RECIPE_V2",
    "load_live_pilot_state_v2",
    "persist_live_pilot_evaluation_v2",
    "plan_live_pilot_step_v2",
    "resolve_live_pilot_binding_v2",
    "run_live_pilot_planning_once_v2",
]
