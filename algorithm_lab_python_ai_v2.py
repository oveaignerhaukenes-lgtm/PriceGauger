"""AI Python model authoring for the independently isolated Algorithm Lab worker.

Generating source is NOT executing it, and the model has no broker/order APIs.
"""
from __future__ import annotations

import requests

from config import openai_api_key, openai_market_model
from strategy_lab_v2_ai import LabAIError, _call_responses_api, _response_text
from algorithm_lab_sandbox_v2 import validate_script

SYSTEM_PROMPT = """Du er en presis kvantutvikler for PriceGauger Forskningslab.
Skriv en ny eller revidert PYTHON-funksjon for historisk PAPER-forskning.

Svar BARE med ren Python-kode, uten markdown eller forklaring.
Obligatorisk API:
def decide(bar, state):
    # bar: dict med 'at','open','high','low','close' fra sist observerte 1m-bar.
    # state: muterbar dict som lever videre fra forrige observerte bar.
    # Returner int -1 for SHORT, 0 for FLAT, +1 for LONG.
    ...

Du får kun én avsluttet bar om gangen. Bygg egen indikatorhistorikk i state,
ikke bruk fremtidige priser, globale datasett eller ekte order/fill-status.
Bruk standard Python uten eksterne biblioteker. Ikke import, fil-/nettverks-I/O,
shell, env, databaser, Saxo eller hemmeligheter. Disse er uansett utilgjengelige
i forskningscontaineren. Hver invokasjon må kjøre raskt og deterministisk.
Sjekk warmup og datahull, ikke anta at 1m gir 10s-fills.
Foretrekk få tydelige parametere og ingen påstander om garantert P/L.
Kode kjøres bare i separat ressursbegrenset Docker-container etter validering,
aldri i PG webserver eller en LIVE trading worker.
"""

DEFAULT_CODE = '''def decide(bar, state):
    # Example: 1m impulse collector, long or flat.
    prices = state.setdefault("closes", [])
    prices.append(float(bar["close"]))
    if len(prices) > 15:
        del prices[0]
    if len(prices) < 11:
        return 0
    momentum_bps = (prices[-1] / prices[-11] - 1.0) * 10000
    return 1 if momentum_bps > 8 else 0
'''


def propose_python_research(*, request: str, current_code: str = DEFAULT_CODE,
                            market: str = "Tech100",
                            post=requests.post) -> str:
    token = openai_api_key()
    if not token:
        raise LabAIError("API_KEY_MISSING", "OpenAI API-key mangler.")
    question = str(request or "").strip()[:1600]
    if not question:
        raise ValueError("Beskriv forskningsstrategien.")
    src = validate_script(current_code)
    body = {
        "model": openai_market_model(),
        "instructions": SYSTEM_PROMPT,
        "input": [
            {"role": "user", "content": "Marked: " + str(market)[:80]},
            {"role": "user", "content": "Eksisterende kode: " + src},
            {"role": "user", "content": "Endring: " + question},
        ],
        "max_output_tokens": 2400, "store": False,
    }
    reply = _response_text(_call_responses_api(post, token=token, body=body)).strip()
    if reply.startswith("```"):
        lines = reply.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            reply = "\n".join(lines[1:-1])
    validate_script(reply)
    import ast
    try:
        tree = ast.parse(reply)
    except SyntaxError:
        raise LabAIError("INVALID_PYTHON", "AI returnerte ugyldig Python.") from None
    if not any(isinstance(node, ast.FunctionDef) and node.name == "decide"
               for node in tree.body):
        raise LabAIError("MISSING_DECIDE", "AI-koden mangler decide(bar, state).")
    return reply


__all__ = ["SYSTEM_PROMPT", "DEFAULT_CODE", "propose_python_research"]
