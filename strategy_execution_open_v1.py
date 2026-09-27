"""Explicit, budget-capped Strategy Lab OPEN through the canonical durable worker."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from autotrader_fast_live_runtime_v2 import FastLiveStateV2, _exact_product_observation, _persist_intent_and_request_v2
from autotrader_live_open_legacy_v2 import (
    ENTRY_MODE_MANUAL_ONLY, ENTRY_MODE_APPROVAL_REQUIRED, approve_open_request_v2,
    code_gate_enabled_v2, load_live_open_config_v2, _account_info, _open_orders_exist,
)
from autotrader_manage_control_v1 import auto_manage_enabled_v1, position_management_enabled_v1
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import _position_observations_v2
from autotrader_strategy_enrollment_v2 import load_strategy_enrollment_v2
from autotrader_strategy_switch_provenance_v2 import grant_user_confirmed_flat_authority_v2
from autotrader_strategy_switch_v2 import _pg_execution_inflight_v2
from database import connect
from research_trade_plan_store_v1 import assert_research_scope_v1, mark_research_handoff_queued_v1
from saxo_provider import LIVE_BASE_URL, configured_client
from strategy_execution_adapter_v1 import require_live_open_budget_support_v1, validate_strategy_execution_binding_v1


@dataclass(frozen=True, slots=True)
class ScopedOpenResultV1:
    request_id: str
    max_notional_nok: float


def queue_strategy_lab_open_v1(*, scope_id: str, strategy_key: str, plan_id: str,
    handoff_id: str, pilot_key: str, account_id: str, uic: int, asset_type: str,
    budget_nok: float, exposure_pct: float) -> ScopedOpenResultV1:
    """Queue one user-approved OPEN, without POSTing to Saxo from Strategy Lab."""
    binding = validate_strategy_execution_binding_v1(scope_id=scope_id, strategy_key=strategy_key,
        plan_id=plan_id, handoff_id=handoff_id, pilot_key=pilot_key, account_id=account_id,
        uic=uic, asset_type=asset_type, budget_nok=budget_nok, exposure_pct=exposure_pct)
    require_live_open_budget_support_v1(binding)
    scope = binding.scope
    if scope.max_exposure_nok <= 0:
        raise ValueError("STRATEGY_LAB_ZERO_EXPOSURE")
    handoff = assert_research_scope_v1(plan_id=plan_id, strategy_key=strategy_key, scope_id=scope_id)
    target = str(json.loads(handoff.payload_json).get("direction", "")).upper()
    if target not in {"LONG", "SHORT"}:
        raise ValueError("STRATEGY_LAB_INVALID_APPROVED_DIRECTION")
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if (enrollment is None or not enrollment.enabled or enrollment.strategy_key != binding.execution_strategy_key
        or enrollment.account_id != account_id or enrollment.uic != int(uic) or enrollment.asset_type != asset_type):
        raise ValueError("STRATEGY_LAB_ENROLLMENT_CHANGED")
    if (not enrollment.live_open_armed or enrollment.entry_mode == ENTRY_MODE_MANUAL_ONLY
        or not code_gate_enabled_v2() or not load_live_open_config_v2().armed):
        raise ValueError("STRATEGY_LAB_CANONICAL_OPEN_NOT_ARMED")
    if auto_manage_enabled_v1(enrollment) or not position_management_enabled_v1(enrollment):
        raise ValueError("STRATEGY_LAB_REQUIRES_ISOLATED_MANUAL_PILOT")
    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("STRATEGY_LAB_PRODUCT_EXECUTION_INFLIGHT")
    with connect() as db:
        competing = db.execute("""SELECT request_id FROM pg_v2_autotrader_execution_requests
          WHERE account_id=? AND uic=? AND asset_type=? AND status IN ('PENDING','APPROVED')
          LIMIT 1""", (account_id, int(uic), asset_type)).fetchone()
    if competing is not None:
        raise ValueError("STRATEGY_LAB_PRODUCT_ALREADY_HAS_QUEUED_REQUEST")
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        raise ValueError("STRATEGY_LAB_SAXO_LIVE_UNAVAILABLE")
    account_key, currency = _account_info(client, account_id)
    equity = load_pilot_equity_v2(pilot_key=pilot_key)
    if currency.upper() != "NOK" or equity.currency.upper() != "NOK" or equity.entry_budget <= 0:
        raise ValueError("STRATEGY_LAB_NOK_EQUITY_REQUIRED")
    if _exact_product_observation(enrollment, _position_observations_v2(client)) is not None:
        raise ValueError("STRATEGY_LAB_REQUIRES_FLAT_EXACT_PRODUCT")
    if _open_orders_exist(client, account_key=account_key, uic=int(uic)):
        raise ValueError("STRATEGY_LAB_WORKING_ORDER_ON_PRODUCT")
    market = client._get("trade/v1/infoprices", params={"AccountKey":account_key,
        "Uic":int(uic),"AssetType":asset_type,"FieldGroups":"InstrumentPriceDetails,Quote"})
    details = market.get("InstrumentPriceDetails") or {}
    quote = market.get("Quote") or {}
    if details.get("IsMarketOpen") is not True or str(quote.get("ErrorCode") or "").strip().lower() not in {"", "none"}:
        raise ValueError("STRATEGY_LAB_MARKET_NOT_EXPLICITLY_OPEN")

    now = datetime.now(timezone.utc)
    intent = str(uuid5(NAMESPACE_URL, f"strategy-lab-open|{scope.scope_id}|{scope.handoff_id}"))
    request_id = str(uuid5(NAMESPACE_URL, f"fast-live-execution|{intent}|OPEN|{target}"))
    state = FastLiveStateV2(pilot_key=pilot_key, strategy_key=enrollment.strategy_key,
        desired_direction=target, last_action_at=now, pending_target_direction=target,
        intent_event_id=intent, intent_signal_at=now, intent_signal="STRATEGY_LAB_APPROVED_OPEN")
    # A confirmed FLAT handoff authorizes the existing OPEN worker; it does not
    # authorize any UI broker POST. The canonical worker still checks its gates.
    grant_user_confirmed_flat_authority_v2(pilot_key=pilot_key, source="STRATEGY_LAB_APPROVED_PLAN")
    created = _persist_intent_and_request_v2(enrollment=enrollment, state=state,
        observed=None, observed_direction="FLAT", budget_amount=scope.max_exposure_nok,
        budget_currency="NOK", supersede_prior=False, execution_scope=scope)
    if not created:
        raise ValueError("STRATEGY_LAB_OPEN_REQUEST_NOT_CREATED")
    if enrollment.entry_mode == ENTRY_MODE_APPROVAL_REQUIRED:
        approve_open_request_v2(pilot_key=pilot_key, request_id=request_id,
                                source="STRATEGY_LAB_APPROVED_PLAN")
    mark_research_handoff_queued_v1(plan_id)
    return ScopedOpenResultV1(request_id=request_id, max_notional_nok=scope.max_exposure_nok)
