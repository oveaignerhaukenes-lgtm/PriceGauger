"""Avoid Loss V1 pilot supervisor: pure close/flat state machine.

No broker orders, database writes, feature activation, or background loops here.
The caller provides independently account-scoped broker evidence. A CLOSE
intent is NOT evidence of a fill; the durable V3 order guard owns submission
and post-order reconciliation. Default operational mode remains OFF.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from autotrader_v3_avoid_loss_v1 import (
    AvoidLossDecisionV1, AvoidLossSettingsV1, AvoidLossStateV1,
    BrokerPnLSampleV1, ConfirmedPositionV1, inspect_open_position_v1,
)

UNRESOLVED_ORDER_STATES = frozenset({"RESERVED","SUBMITTING","SUBMITTED","UNKNOWN"})
TERMINAL_ORDER_STATES = frozenset({"RECONCILED","REJECTED"})


@dataclass(frozen=True, slots=True)
class AvoidLossPilotPlanV1:
    status: str
    reason: str
    next_state: AvoidLossStateV1 | None
    close_needed: bool = False
    broker_flat_confirmed: bool = False
    pnl_pct: float | None = None


def _plan(status: str, reason: str, state: AvoidLossStateV1 | None = None,
          *, close: bool = False, flat: bool = False,
          pnl_pct: float | None = None) -> AvoidLossPilotPlanV1:
    return AvoidLossPilotPlanV1(status,reason,state,close,flat,pnl_pct)


def plan_avoid_loss_pilot_v1(
    *, position: ConfirmedPositionV1 | None,
    state: AvoidLossStateV1 | None,
    sample: BrokerPnLSampleV1 | None,
    exact_net_rows: Sequence | None,
    exact_individual_rows: Sequence | None,
    no_broker_working_orders: bool | None,
    durable_order_state: str | None,
    market_is_open: bool | None,
    confirmed_close_fill: bool = False,
    now: datetime,
    policy: AvoidLossSettingsV1 = AvoidLossSettingsV1(),
) -> AvoidLossPilotPlanV1:
    """Produce a fail-closed plan for one Saxo account/product boundary.

    Neither flat net inventory nor a 'successful' order response is sufficient
    for FLAT. Both broker GETs must return an empty result, no working Saxo
    order and no unresolved durable request. UNKNOWN and partial fills block.
    """
    if now.tzinfo is None:
        return _plan("UNPROTECTED","UTC_CLOCK_INVALID",state)
    if exact_net_rows is None or exact_individual_rows is None:
        return _plan("UNPROTECTED","BROKER_POSITION_READ_MISSING",state)
    if not isinstance(exact_net_rows,(list,tuple)) or not isinstance(exact_individual_rows,(list,tuple)):
        return _plan("UNPROTECTED","BROKER_POSITION_READ_INVALID",state)
    order=(str(durable_order_state or "").upper())
    if order and order not in UNRESOLVED_ORDER_STATES | TERMINAL_ORDER_STATES:
        return _plan("UNPROTECTED","DURABLE_ORDER_STATE_UNKNOWN",state)
    if no_broker_working_orders is not True:
        return _plan("WAIT_ORDER","BROKER_WORKING_ORDERS_UNVERIFIED",state)
    is_flat=(not exact_net_rows and not exact_individual_rows)
    if is_flat:
        if order in UNRESOLVED_ORDER_STATES:
            return _plan("WAIT_ORDER","BROKER_FLAT_BUT_ORDER_UNRESOLVED",state)
        if position is not None:
            # Only a future durable reconciliation coordinator may retire an
            # anchor after CLOSE audit. This flags readiness to retire, not
            # a license to erase history by itself.
            if order != "RECONCILED" or confirmed_close_fill is not True:
                return _plan("UNPROTECTED","BROKER_FLAT_WITHOUT_CONFIRMED_CLOSE_AUDIT",state)
            if state is None or not state.exit_pending:
                return _plan("UNPROTECTED","CLOSE_LATCH_MISSING_ON_FLAT",state)
            return _plan("BROKER_FLAT_VERIFIED","BOTH_POSITION_READS_EMPTY_AND_AUDIT_CONFIRMED",state,flat=True)
        return _plan("FLAT","NO_POSITION_NO_OPEN_REQUEST",None,flat=True)
    if position is None:
        return _plan("UNPROTECTED","OPEN_POSITION_HAS_NO_CONFIRMED_ANCHOR",state)
    if len(exact_net_rows)!=1 or len(exact_individual_rows)!=1:
        return _plan("UNPROTECTED","AMBIGUOUS_BROKER_POSITIONS",state)
    netrow,individual=exact_net_rows[0],exact_individual_rows[0]
    try:
        base=individual["PositionBase"]
        netbase=netrow["NetPositionBase"]
        amount=float(base["Amount"])
        long_amount=float(netbase.get("AmountLong") or 0)
        short_amount=float(netbase.get("AmountShort") or 0)
        same_boundary=(
            str(individual.get("PositionId") or "")==position.position_token
            and str(base.get("AccountId") or base.get("PositionsAccount") or "")==position.account_id
            and all(str(x.get("AssetType") or "")==position.asset_type
                    and int(x.get("Uic") or -1)==position.uic for x in (base,netbase))
            and (not str(netbase.get("AccountId") or netbase.get("PositionsAccount") or "")
                 or str(netbase.get("AccountId") or netbase.get("PositionsAccount"))==position.account_id)
            and abs(abs(amount)-abs(position.signed_amount))<=1e-9
            and abs(long_amount-short_amount-position.signed_amount)<=1e-9
            and str(base.get("Status") or "").lower() in {"open","partiallyclosed"}
        )
    except (TypeError,ValueError,KeyError,OverflowError,AttributeError):
        same_boundary=False
    if not same_boundary:
        return _plan("UNPROTECTED","BROKER_POSITION_ANCHOR_MISMATCH",state)
    if state is not None and state.position_key!=position.key:
        return _plan("UNPROTECTED","STOP_STATE_ANCHOR_MISMATCH",state)
    if order in UNRESOLVED_ORDER_STATES:
        return _plan("WAIT_ORDER","UNRESOLVED_V3_ORDER_NO_RETRY",state)
    if order in TERMINAL_ORDER_STATES and state is not None and state.exit_pending:
        return _plan("UNPROTECTED","CLOSE_TERMINAL_BUT_POSITION_STILL_OPEN",state)
    if market_is_open is not True:
        return _plan("WAIT_MARKET" if market_is_open is False else "UNPROTECTED",
                     "MARKET_CLOSED" if market_is_open is False else "MARKET_STATE_UNKNOWN",state)
    if sample is None:
        return _plan("UNPROTECTED","VERIFIED_NET_PNL_SAMPLE_MISSING",state)
    decision:AvoidLossDecisionV1=inspect_open_position_v1(
        position=position,sample=sample,state=state,now=now,policy=policy)
    if decision.action=="BLOCKED":
        return _plan("UNPROTECTED","NET_PNL_EVIDENCE_INVALID",state)
    if decision.action in {"REQUEST_CLOSE","WAIT_RECONCILE"}:
        if decision.state is None or not decision.state.exit_pending:
            return _plan("UNPROTECTED","STOP_LATCH_NOT_DURABLE",state)
        # This intent is only eligible for dispatch by a separate, explicit,
        # account-locked V3 execution adapter after saving the sticky state.
        return _plan("CLOSE_REQUIRED",decision.reason,decision.state,
                     close=True,pnl_pct=decision.pnl_pct)
    return _plan("MONITORING","POSITION_WATCHED",decision.state,pnl_pct=decision.pnl_pct)


__all__=["AvoidLossPilotPlanV1","plan_avoid_loss_pilot_v1"]
