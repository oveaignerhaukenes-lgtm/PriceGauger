"""Opt-in V3 LIVE loss-manager overlay using verified, fresh model decisions.

A model never touches Saxo or selects a new position. The ordinary V3 pipeline
reduces an existing position on a causal SHADOW analysis, then uses exactly the
same Saxo reconciliation and order prechecks as every deterministic strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite

from autotrader_v3_ai_decision_memory_v1 import load_ai_decisions_v1
from autotrader_v3_domain import TargetInventoryV3, centilots_v3, lots_v3
from trading_desk import utc

MODIFIER_KEY_V3="ai-loss-manager"
ADVICE_MAX_AGE_SECONDS=100
CONFIDENCE_FLOOR=.60


@dataclass(frozen=True)
class AILiveAdviceV3:
    decision_id: str
    action: str
    evaluated_at: datetime
    confidence: float
    current_quantity: float
    reason: str


def verified_live_ai_advice_v3(
    *, instance_id: str, account_id: str, instrument_id: int,
    strategy_key: str, timeframe: str, actual_amount: float,
    verified_open_pnl: float, now: datetime, db_path="pricegauger.db",
    max_age_seconds=ADVICE_MAX_AGE_SECONDS,
) -> AILiveAdviceV3 | None:
    """Find a recent scoped decision whose exact held position still matches.

    All missing, future, nonloss, stale and incompatible evidence is ignored.
    The advice remains a suggestion until a V3 pipeline modifier applies it.
    """
    if not (isfinite(float(actual_amount)) and isfinite(float(verified_open_pnl))):
        return None
    if abs(float(actual_amount))<1e-10 or float(verified_open_pnl)>=0:
        return None
    current_time=utc(now)
    decisions=load_ai_decisions_v1(
        instance_id=instance_id,account_id=account_id,
        instrument_id=instrument_id,limit=12,db_path=db_path)
    for row in decisions:
        if str(row["mode"])!="SHADOW":
            continue
        timestamp=utc(row["evaluated_at"])
        seconds=(current_time-timestamp).total_seconds()
        if seconds<0 or seconds>int(max_age_seconds):
            continue
        # A newer HOLD cancels an older FLAT; no falling through to stale advice.
        if str(row["strategy_key"])!=str(strategy_key):
            return None
        try:
            evidence=json.loads(row["evidence_json"])
            snapshot=evidence["snapshot"]
            position=snapshot["position"]
            if (str(snapshot["strategy"])!=str(strategy_key)
                or str(snapshot["timeframe"])!=str(timeframe)
                or str(snapshot["source"])!="V3_SHADOW_ACCOUNT_SCOPED"):
                return None
            quantity=float(position["quantity_abs"])
            p_at_review=float(position["saxo_open_pnl_account_currency"])
            if (not isfinite(quantity) or not isfinite(p_at_review)
                or p_at_review>=0 or abs(quantity-abs(actual_amount))>1e-8
                or position["direction"]!=("LONG" if actual_amount>0 else "SHORT")):
                return None
            # Verify the decision's evidence was not collected after evaluation.
            if utc(row["evidence_as_of"])>timestamp:
                return None
            confidence=float(row["confidence"])
            if not isfinite(confidence) or confidence<CONFIDENCE_FLOOR:
                return None
            action=str(row["action"])
            if action not in {"HOLD","FLAT","REDUCE","REVERSE"}:
                return None
            return AILiveAdviceV3(str(row["decision_id"]),action,timestamp,
                                  confidence,quantity,str(row["reason"]))
        except (KeyError,TypeError,ValueError,OverflowError):
            return None
    return None


@dataclass(frozen=True)
class AILossManagerLiveModifierV3:
    """Existing-position defence. An AI never increases or opens exposure."""

    actual_inventory: float
    advice: AILiveAdviceV3
    key: str=MODIFIER_KEY_V3

    def apply(self, trader, target: TargetInventoryV3):
        actual=float(self.actual_inventory)
        current=float(target.amount)
        if abs(actual)<1e-10 or current*actual<=0:
            return target,"No AI override: base strategy already exiting or flat"
        if abs(current)<abs(actual)-1e-10:
            return target,"No AI override: base strategy already reducing"
        if self.advice.action=="HOLD":
            return target,"AI HOLD: deterministic strategy unchanged"
        if self.advice.action in ("FLAT","REVERSE"):
            # REVERSE is a FLAT intervention first. AI cannot create an
            # opposite-side Saxo exposure from a proposal in this version.
            return TargetInventoryV3(0.),f"AI {self.advice.action}: exit existing position; {self.advice.decision_id}"
        if self.advice.action=="REDUCE":
            steps=abs(centilots_v3(actual))
            if steps<=1:
                # A 0.01-lot position cannot be halved. Do not create a
                # rounding-induced full close from a REDUCE recommendation.
                return target,"AI REDUCE under minimum trade step: no action"
            # Remove exactly one minimum increment; all remaining execution
            # constraints apply downstream in V3 LIVE.
            reduced_units=(steps-1)*(1 if actual>0 else -1)
            proposal=TargetInventoryV3(float(lots_v3(reduced_units)))
            return proposal,f"AI REDUCE one Saxo increment; {self.advice.decision_id}"
        return target,"No actionable AI proposal"


__all__=["MODIFIER_KEY_V3","AILiveAdviceV3","AILossManagerLiveModifierV3",
         "verified_live_ai_advice_v3"]
