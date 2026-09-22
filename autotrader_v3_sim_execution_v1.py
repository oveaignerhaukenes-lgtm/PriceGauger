from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from autotrader_v3_domain import DecisionSnapshotV3
from autotrader_v3_execution_plan_v1 import ExecutionPlanV3, ExecutionStepV3, plan_execution_v3
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoOrderRequest, SaxoTradingClient, SaxoTradingSafetyError


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
                               submitted_intent_ids: set[str]) -> dict:
    """SIM-only, exactly-once caller-state gate for the first 0.01 v3 execution test."""
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
    submitted_intent_ids.add(intent.intent_id)
    response=trading.place_order(order,confirm_sim=True)
    positions=trading.net_positions_me(account_id=intent.account_id,uic=intent.instrument.uic)
    return {"intent_id":intent.intent_id,"order_response":response,"net_positions":positions}


__all__=["ExecutionIntentV3","MAX_FIRST_TEST_DELTA_V3","build_execution_intent_v3","execute_first_test_step_v3","plan_execution_v3"]
