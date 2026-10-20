"""On-demand, as-of Strategy Lab AI research dialogue (no broker capability)."""
from __future__ import annotations

import json
from hashlib import sha256
from math import isfinite
from typing import Mapping,Sequence
import requests

from config import openai_api_key,openai_market_model

URL="https://api.openai.com/v1/responses"


def build_lab_asof_evidence_v2(*,strategy:str,selected_at,points:Sequence,
                                events:Sequence,market:str,product_key:str,
                                costs_source:str)->dict:
    from strategy_lab_v2_replay import utc
    cursor=utc(selected_at)
    observed=[p for p in points if utc(p.at)<=cursor]
    if not observed:raise ValueError("No completed PAPER bars at cursor")
    active=observed[-1]
    history=observed[-24:]
    selected_events=[e for e in events if utc(e.at)<=cursor][-12:]
    return {
        "source":"STRATEGY_LAB_V2_PAPER_ASOF",
        "as_of":cursor.isoformat(),
        "strategy":strategy,"market":market,"product":product_key,
        "cost_source":costs_source,
        "position_lots":active.lots,
        "paper_nav_nok":active.nav_nok,
        "closed_prices":[{"time":p.at.isoformat(),"close":p.price,
                          "macd_hist":p.macd_hist,"lots":p.lots,"signal":p.signal}
                         for p in history],
        "past_paper_trades":[{"time":e.at.isoformat(),"kind":e.kind,
                               "price":e.price,"after_lots":e.after_lots,
                               "cost_nok":e.cost_nok,"reason":e.reason}
                              for e in selected_events],
        "limitations":(
            "SIM uses current Saxo indicative costs or manual scenario, "
            "next-1m-open fills, no historical BBO/slippage, no exact Saxo P/L. "
            "Only timestamps <= as_of. No new LIVE order rights."
        ),
    }


def lab_ai_evidence_fingerprint_v2(evidence:Mapping)->str:
    return sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False,
                             separators=(",",":")).encode()).hexdigest()


def _response_text(payload:Mapping)->str:
    items=payload.get("output") or []
    chunks=[]
    for item in items:
        if not isinstance(item,dict):continue
        for content in item.get("content") or []:
            if (isinstance(content,dict) and
                content.get("type")=="output_text" and
                isinstance(content.get("text"),str)):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def ask_lab_ai_v2(*,evidence:Mapping,question:str,
                  history:Sequence[Mapping]=(),key:str|None=None,
                  model:str|None=None,post=requests.post)->str:
    question=str(question or "").strip()[:900]
    if not question:raise ValueError("Write a research question")
    token=key if key is not None else openai_api_key()
    if not token:raise ValueError("No OpenAI API key configured")
    if evidence.get("source")!="STRATEGY_LAB_V2_PAPER_ASOF":
        raise ValueError("Only as-of lab evidence can be sent to AI")
    # Never include any user/account credentials, unrequested Saxo keys,
    # future bars, or a prompt granting brokerage/execution authority.
    turns=[{"role":"user","content":str(x.get("question",""))[:500]},
           {"role":"assistant","content":str(x.get("answer",""))[:1500]}
           for x in []] if False else []
    for x in history[-4:]:
        turns.extend((
            {"role":"user","content":str(x.get("question",""))[:500]},
            {"role":"assistant","content":str(x.get("answer",""))[:1500]},
        ))
    context=json.dumps(evidence,ensure_ascii=False,sort_keys=True,allow_nan=False)
    resp=post(URL,
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
        json={
            "model":model or openai_market_model(),
            "instructions":(
                "You are a skeptical trading research analyst. Work ONLY from "
                "the as-of historical data supplied. Do not infer future prices, "
                "past hidden fills, broker-verified net P/L, or live order rights. "
                "Explain the mechanical strategy, its entry/exit rationale, "
                "competing explanations, signal latency, and how to A/B test a "
                "proposed change net of costs. Respond in Norwegian, compactly. "
                "This is PAPER RESEARCH. Never provide an instruction to "
                "submit trades or change an account."
            ),
            "input":[{"role":"user","content":"Evidence (immutable as-of): "+context},
                     *turns,{"role":"user","content":question}],
            "max_output_tokens":650,
            "store":False,
        },timeout=32)
    resp.raise_for_status()
    answer=_response_text(resp.json())
    if not answer:raise ValueError("AI response had no text")
    return answer


__all__=["build_lab_asof_evidence_v2","lab_ai_evidence_fingerprint_v2",
         "ask_lab_ai_v2"]
