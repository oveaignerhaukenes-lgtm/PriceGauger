from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from autotrader_v3_domain import DecisionSnapshotV3
from autotrader_v3_execution_plan_v1 import ExecutionPlanV3, ExecutionStepV3, plan_execution_v3
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest, SaxoTradingClient, SaxoTradingSafetyError
from autotrader_v3_execution_store_v1 import reserve_intent_v3, mark_intent_attempted_v3
from autotrader_v3_sim_authority_v1 import any_sim_authority_armed_v3


MAX_FIRST_TEST_DELTA_V3 = 0.01


@dataclass(frozen=True, slots=True)
class ExecutionIntentV3:
    intent_id: str
    trader_id: str
    step: ExecutionStepV3
    account_key: str
    account_id: str
    instrument: SaxoInstrument

    def order_request(self) -> SaxoOrderRequest:
        if self.step.action not in {"OPEN", "ADD", "REDUCE", "CLOSE"}:
            raise SaxoTradingSafetyError("non-order execution step cannot become a Saxo order")
        if self.step.action in {"OPEN", "ADD"}:
            side = "Buy" if self.step.direction == "LONG" else "Sell"
        else:
            side = "Sell" if self.step.direction == "LONG" else "Buy"
        return SaxoOrderRequest(
            account_key=self.account_key, instrument=self.instrument,
            amount=self.step.amount, buy_sell=side, external_reference=self.intent_id[:50],
        )


def build_execution_intent_v3(*, snapshot: DecisionSnapshotV3, step: ExecutionStepV3,
                              account_key: str, account_id: str, instrument: SaxoInstrument,
                              decision_key: str) -> ExecutionIntentV3:
    identity="|".join((snapshot.trader_id,decision_key,account_id,str(instrument.uic),instrument.asset_type,
                       step.action,step.direction,f"{step.amount:.12g}"))
    return ExecutionIntentV3("pg-v3-"+sha256(identity.encode()).hexdigest()[:32],
                             snapshot.trader_id,step,account_key,account_id,instrument)


def execute_first_test_step_v3(*, trading: SaxoTradingClient, intent: ExecutionIntentV3,
                               submitted_intent_ids: set[str], decision_key: str = "", db_path: str = "pricegauger.db") -> dict:
    """Dormant broker primitive for a future explicit execution test; never used by simulator runtime."""
    if any_sim_authority_armed_v3(db_path=db_path):
        raise SaxoTradingSafetyError("v3 simulator authority is armed; broker mutation is blocked")
    if intent.intent_id in submitted_intent_ids:
        raise SaxoTradingSafetyError("v3 intent already attempted; automatic retry blocked")
    if intent.step.action not in {"OPEN","ADD","REDUCE","CLOSE"}:
        raise SaxoTradingSafetyError("v3 execution step is not directly executable")
    if intent.step.amount <= 0 or intent.step.amount > MAX_FIRST_TEST_DELTA_V3 + 1e-12:
        raise SaxoTradingSafetyError("first v3 test is hard-capped to 0.01 per mutation")
    order=intent.order_request()
    precheck=trading.precheck(order)
    if str(precheck.get("PreCheckResult") or "").lower() != "ok" or precheck.get("PreTradeDisclaimers"):
        raise SaxoTradingSafetyError("Saxo precheck did not clear v3 execution")
    if not reserve_intent_v3(intent_id=intent.intent_id, decision_key=decision_key or intent.intent_id, payload={"trader_id":intent.trader_id,"action":intent.step.action,"direction":intent.step.direction,"amount":intent.step.amount,"account_id":intent.account_id,"uic":intent.instrument.uic,"asset_type":intent.instrument.asset_type}, db_path=db_path):
        raise SaxoTradingSafetyError("v3 intent already exists durably; automatic retry blocked")
    submitted_intent_ids.add(intent.intent_id)
    mark_intent_attempted_v3(intent.intent_id, db_path=db_path)
    response=trading.place_order(order,confirm_sim=True)
    positions=trading.net_positions_me(account_id=intent.account_id,uic=intent.instrument.uic)
    return {"intent_id":intent.intent_id,"order_response":response,"net_positions":positions}


__all__=["ExecutionIntentV3","MAX_FIRST_TEST_DELTA_V3","build_execution_intent_v3","execute_first_test_step_v3","plan_execution_v3"]
