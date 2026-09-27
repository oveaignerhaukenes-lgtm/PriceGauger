from __future__ import annotations
import json
from pathlib import Path
from typing import Mapping, Sequence
import requests
from config import openai_api_key, openai_market_model
from market_chat import OPENAI_RESPONSES_URL, _response_output_text
from research_strategy_store_v1 import load_research_events_v1
from research_trade_plan_store_v1 import load_research_trade_plans_v1
from strategy_factor_store_v1 import load_strategy_factors_v1

PROMPT_VERSION="strategy-lab-discussion-v1"
MAX_MESSAGES=40

def answer_strategy_discussion_v1(strategy_key: str, messages: Sequence[Mapping[str, object]],
                                  *, api_key: str | None=None, model: str | None=None,
                                  timeout_seconds: float=60.0) -> str:
    key=(api_key if api_key is not None else openai_api_key()).strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is not configured")
    events=load_research_events_v1(strategy_key)
    plans=load_research_trade_plans_v1(strategy_key)
    factors=load_strategy_factors_v1(strategy_key)
    context={
        "strategy_key":strategy_key,
        "hypothesis_timeline":[{
            "version":e.version,"type":e.event_type,"verdict":e.verdict,
            "title":e.title,"body":e.body,"observed_at":e.observed_at.isoformat()
        } for e in events],
        "factor_configuration":[{
            "factor_key":f.factor_key,"label":f.label,"enabled":f.enabled,
            "category":f.category,"rationale":f.rationale
        } for f in factors],
        "trade_plans":[{
            "plan_id":p.plan_id,"version":p.hypothesis_version,"status":p.status,
            "instrument":p.instrument_label,"direction":p.direction,
            "probability_pct":p.probability_pct,"capital_pct":p.capital_pct,\n            "budget_nok":p.budget_nok,"exposure_pct":p.exposure_pct,
            "stop_loss_pct":p.stop_loss_pct,"trail_activation_pct":p.trail_activation_pct,
            "trailing_distance_pct":p.trailing_distance_pct,"event_policy":p.event_policy,
            "rationale":p.rationale
        } for p in plans[:12]],
    }
    instructions=(
        "You are the Strategy Lab research partner inside PriceGauger. The persisted strategy "
        "timeline, factor configuration and Trade Plans below are shared memory and authoritative history. Help the user "
        "criticise, falsify, refine and compare the strategy. Never silently rewrite prior hypotheses; "
        "propose a new version when a material premise changes. Distinguish evidence, inference and "
        "uncertainty. Probability estimates are ex-ante judgments, not guarantees. You have no execution "
        "authority and must not claim orders were placed. You may propose precise DRAFT Execution Plan changes, including budget_nok, exposure_pct, stop, trailing and scale-down, but never claim they were persisted or approved unless the UI/store confirms it. Live actions require explicit user approval in Strategy Lab. Reply in Norwegian unless asked otherwise.\n"
        f"Prompt version: {PROMPT_VERSION}\nSTRATEGY MEMORY:\n"
        + json.dumps(context,ensure_ascii=False,default=str)
    )
    recent=[{"role":str(x.get("role") or "user"),"content":str(x.get("content") or "")}
            for x in messages[-MAX_MESSAGES:] if str(x.get("content") or "").strip()]
    response=requests.post(OPENAI_RESPONSES_URL,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":(model or openai_market_model()),"store":False,"instructions":instructions,"input":recent},
        timeout=timeout_seconds)
    response.raise_for_status()
    return _response_output_text(response.json())
