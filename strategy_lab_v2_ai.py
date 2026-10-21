"""On-demand, as-of Strategy Lab AI research dialogue (no broker capability)."""
from __future__ import annotations

import json
import logging
from hashlib import sha256
from typing import Mapping,Sequence
import requests

from config import openai_api_key,openai_market_model

URL="https://api.openai.com/v1/responses"
LOGGER=logging.getLogger("pricegauger.strategy_lab_v2_ai")


class LabAIError(ValueError):
    """Non-sensitive diagnostic suitable for end users and error-code logs."""

    def __init__(self,code:str,message:str):
        self.code=code
        super().__init__(message)


def _safe_api_error(exc:Exception)->LabAIError:
    resp=getattr(exc,"response",None)
    status=getattr(resp,"status_code",None)
    if status in (401,403):
        return LabAIError("API_AUTH","OpenAI avviste API-tilgangen (HTTP %s). Kontroller nøkkel/rettigheter."%status)
    if status==429:
        return LabAIError("API_LIMIT","OpenAI meldte om bruksgrense eller kapasitetsbegrensning (HTTP 429).")
    if status is not None:
        return LabAIError("API_HTTP","OpenAI API svarte med HTTP %s. Prøv igjen senere."%status)
    return LabAIError("API_CONNECTION","Forbindelsen til OpenAI ble avbrutt. Prøv igjen.")




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
    direct=payload.get("output_text")
    if isinstance(direct,str) and direct.strip():
        return direct.strip()
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


def _call_responses_api(post,*,token:str,body:dict)->Mapping:
    try:
        response=post(
            URL,
            headers={"Authorization":"Bearer "+token,
                     "Content-Type":"application/json"},
            json=body,timeout=40)
        response.raise_for_status()
        result=response.json()
    except requests.RequestException as exc:
        raise _safe_api_error(exc) from None
    except (ValueError,TypeError):
        raise LabAIError("API_BAD_JSON","OpenAI svarte med et ugyldig JSON-dokument.") from None
    if not isinstance(result,dict):
        raise LabAIError("API_BAD_JSON","OpenAI-responsen hadde ugyldig format.")
    return result


def ask_lab_ai_v2(*,evidence:Mapping,question:str,
                  history:Sequence[Mapping]=(),key:str|None=None,
                  model:str|None=None,post=requests.post)->str:
    question=str(question or "").strip()[:900]
    if not question:
        raise LabAIError("QUESTION_EMPTY","Skriv et spørsmål før analysen startes.")
    token=key if key is not None else openai_api_key()
    if not token:
        raise LabAIError("API_KEY_MISSING","OpenAI API-nøkkel mangler i webtjenestens konfigurasjon.")
    if evidence.get("source")!="STRATEGY_LAB_V2_PAPER_ASOF":
        raise LabAIError("INVALID_EVIDENCE","Only as-of lab evidence can be sent to AI")
    # Never include account/API credentials, future bars, or brokerage authority.
    turns=[]
    for x in history[-4:]:
        turns.extend((
            {"role":"user","content":str(x.get("question",""))[:500]},
            {"role":"assistant","content":str(x.get("answer",""))[:1500]},
        ))
    try:
        context=json.dumps(evidence,ensure_ascii=False,sort_keys=True,
                           allow_nan=False)
    except (ValueError,TypeError):
        raise LabAIError(
            "INVALID_NUMERIC_EVIDENCE",
            "Historiske analysedata inneholder ugyldige tall (NaN/Inf) eller uleselige verdier."
        ) from None
    body={
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
        "max_output_tokens":1600,
        "store":False,
    }
    try:
        for attempt in range(2):
            result=_call_responses_api(post,token=token,body=body)
            answer=_response_text(result)
            if answer:
                return answer
            status=str(result.get("status") or "").lower()
            details=result.get("incomplete_details")
            reason=(str(details.get("reason") or "")
                    if isinstance(details,dict) else "")
            # GPT reasoning can consume an entire small output budget,
            # leaving no visible text. Retry ONCE with more tokens.
            if (attempt==0 and status=="incomplete"
                and reason=="max_output_tokens"):
                body["max_output_tokens"]=3200
                LOGGER.info("strategy_lab_v2_ai_retry code=OUTPUT_BUDGET")
                continue
            if status=="incomplete":
                raise LabAIError(
                    "MODEL_INCOMPLETE",
                    "AI-modellen fullførte ikke svaret (%s). Prøv igjen."%
                    (reason if reason in ("max_output_tokens","content_filter") else "ukjent årsak"),
                )
            if status=="failed":
                raise LabAIError("MODEL_FAILED","AI-modellen rapporterte mislykket kjøring.")
            raise LabAIError(
                "MODEL_EMPTY_RESPONSE",
                "OpenAI svarte uten tekst. Prøv igjen eller velg et annet analysetidspunkt.",
            )
    except LabAIError as exc:
        # Intentionally log ONLY a diagnostic code, never prompts, account
        # metadata, API responses, token or request headers.
        LOGGER.warning("strategy_lab_v2_ai_failed code=%s",exc.code)
        raise


__all__=["LabAIError","build_lab_asof_evidence_v2",
         "lab_ai_evidence_fingerprint_v2","ask_lab_ai_v2"]
