"""LLM-assisted strategy drafting for Algorithm Lab v1.

The model never receives broker credentials and only outputs a bounded JSON
plan. It cannot execute code, query arbitrary SQL or authorize LIVE orders.
"""
from __future__ import annotations

import json
import logging
from typing import Mapping, Sequence

import requests

from algorithm_lab_v1 import PRESETS, validate_plan
from config import openai_api_key, openai_market_model
from strategy_lab_v2_ai import LabAIError, _call_responses_api, _response_text

LOGGER = logging.getLogger("pricegauger.algorithm_lab.ai")

ALGORITHM_DESIGN_PROMPT = """Du er senior kvantutvikler for PriceGauger Algorithm Lab, en ren PAPER-simulator.

Oppgaven er å oversette brukerens hypotese til en EKSAKT validerbar,
deterministisk algoritmebeskrivelse. Returner KUN JSON uten markdown:
{"plan":{"kind":"trend|impulse","side":"long|short",
"regime_rule":"none|spread|slope|both",
"lookback":3,"entry_bps":3.0,"exit_bps":3.0,
"fade_bps":0.0,"max_hold":60},
"rationale":"kort norsk forklaring",
"test_notes":"spesifikke begrensninger og A/B-test"}

Planfeltene må være nøyaktig de åtte oppgitte. lookback heltall 1–30
(antall lukkede 1m-barer), max_hold heltall 1–240 (1m-barer);
entry_bps >0 og <=500, exit_bps/fade_bps 0–500.
Trend krever regime_rule spread, slope eller both; 30m MACD 12/26/9
beregnes kun på fullt ferdige, sammenhengende 30m-barer.
spread betyr MACD minus signal-linjen >0 for oppregime, <0 for nedregime.
slope betyr at forskjellen stiger eller faller fra forrige ferdige 30m-bar.
both krever enighet. Impulse kan bruke none (uavhengig av 30m).
Alle posisjoner er LONG/FLAT eller SHORT/FLAT og høyst én tranche.
Signal ved ferdig 1m-close kan fylles tidligst ved neste reelle 1m-open.
Ingen framtidige data, fremtidspivoter, historiske 'perfekte' fills,
syntetiske 1s-data, ordre, kontoendring, filoperasjoner eller SQL.
Impuls via 1m er BARE en grov baselinemodell, ikke dokumentert 10s-capture.
Vurder eksplisitt spread, slippage, finansiering og out-of-sample før
lønnsomhetskonklusjon. Ikke lov garantert profitt.
Hold foreslått modell nær brukerens hypotese; begrunn endringer.
Du kan ikke legge til nye felter, Python-kode, biblioteker eller funksjoner.
Hvis ønsket funksjon krever nye primitives, forklar i test_notes og
foreslå nærmeste lovlige eksperiment uten å late som funksjonen støttes.
"""


def _extract_json(answer: str) -> dict:
    value = str(answer or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            value = "\n".join(lines[1:-1])
    try:
        obj = json.loads(value)
    except (ValueError, TypeError):
        raise LabAIError("INVALID_DRAFT_JSON", "AI svarte ikke med gyldig modell-JSON.") from None
    if not isinstance(obj, dict) or set(obj) != {"plan", "rationale", "test_notes"}:
        raise LabAIError("INVALID_DRAFT_SCHEMA", "AI svarte med feil modellformat.")
    if any(not isinstance(obj.get(k), str) for k in ("rationale", "test_notes")):
        raise LabAIError("INVALID_DRAFT_SCHEMA", "Modellforklaringen mangler.")
    try:
        plan = validate_plan(obj["plan"])
    except (TypeError, ValueError) as exc:
        raise LabAIError("INVALID_DRAFT_PLAN", "AI-generert modell brøt sikkerhetsskjemaet: " + str(exc)) from None
    return {"plan": plan,
            "rationale": obj["rationale"][:900],
            "test_notes": obj["test_notes"][:900]}


def propose_algorithm(*, request: str, current_plan: Mapping, market: str,
                      observed_closes: Sequence[Mapping] = (),
                      model: str | None = None, post=requests.post) -> dict:
    """On-demand, read-only remote AI drafting, never strategy execution."""
    question = str(request or "").strip()[:1800]
    if not question:
        raise LabAIError("EMPTY_REQUEST", "Beskriv ønsket endring.")
    plan = validate_plan(dict(current_plan))
    token = openai_api_key()
    if not token:
        raise LabAIError("API_KEY_MISSING", "OPENAI_API_KEY er ikke konfigurert.")
    # No account IDs, auth tokens, DB schema, raw news/private data, or future bars.
    evidence = {"market": str(market)[:90],
                "current_plan": plan,
                "allowed_presets": PRESETS,
                "observed_closed_1m": tuple(observed_closes)[-24:],
                "historical_data_limit": "Utvalgte allerede lukkede 1m-priser; ikke full rådatabase",
                "execution": "PAPER-only"}
    body = {"model": model or openai_market_model(),
            "instructions": ALGORITHM_DESIGN_PROMPT,
            "input": [{"role": "user", "content":
                       "Forskningskontekst: " + json.dumps(
                           evidence, ensure_ascii=False, allow_nan=False)},
                      {"role": "user", "content": question}],
            "max_output_tokens": 1400,
            "store": False}
    try:
        payload = _call_responses_api(post, token=token, body=body)
        return _extract_json(_response_text(payload))
    except LabAIError as exc:
        LOGGER.warning("algorithm_lab_ai_error code=%s", exc.code)
        raise


__all__ = ["ALGORITHM_DESIGN_PROMPT", "propose_algorithm", "_extract_json"]
