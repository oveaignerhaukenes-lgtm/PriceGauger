"""Evening-only research analyst. Reads immutable paper evidence, never controls trading."""
from __future__ import annotations

import json
import os
from collections import defaultdict

import requests

from database import connect
from live_sim_lab_store_v1 import ensure_lab_schema, lab_snapshot


REPORT_PROMPT_VERSION = "lsim-four-tasks-v1"
MIN_OBSERVATION_BARS = 30
RESPONSES_URL = "https://api.openai.com/v1/responses"


def prepare_evidence(variants, regime_memory):
    """Small, numeric report with paired controls to prevent narrative-only conclusions."""
    usable = [v for v in variants if v["last_bar"]]
    by_config = {
        (v["family"],v["signal_tf"],v["regime_tf"],v["max_exposure"],v["modifier"]):v
        for v in usable
    }
    pairs = []
    for v in usable:
        if v["modifier"] == "none":
            continue
        baseline = by_config.get(
            (v["family"],v["signal_tf"],v["regime_tf"],v["max_exposure"],"none"))
        if baseline is None:
            continue
        pairs.append({
            "candidate_id":v["experiment_id"],"control_id":baseline["experiment_id"],
            "family":v["family"],"signal_tf":v["signal_tf"],"regime_tf":v["regime_tf"],
            "modifier":v["modifier"],"exposure":v["max_exposure"],
            "delta_nav_return_percentage_points":round(v["return_pct"]-baseline["return_pct"],5),
            "delta_max_drawdown_percentage_points":round(
                v["max_drawdown_pct"]-baseline["max_drawdown_pct"],5),
            "delta_trade_count":v["trades"]-baseline["trades"],
        })
    regimes_by_id = defaultdict(list)
    for m in regime_memory:
        if m["regime"] == "WARMUP":
            continue
        regimes_by_id[m["experiment_id"]].append({
            "regime":m["regime"],"bars":int(m["observed_bars"]),
            "sum_delta_nav":round(float(m["sum_delta_nav"]),5),
        })
    return {
        "prompt_version":REPORT_PROMPT_VERSION,
        "experiment_count":len(variants),
        "observed_experiment_count":len(usable),
        "model_type":"LAB_NATIVE_MACD_PROXY_NOT_PRODUCTION_PARITY",
        "virtual_cost_bps_per_turnover":5.0,
        "variants":[{
            "id":v["experiment_id"],"family":v["family"],"signal_tf":v["signal_tf"],
            "regime_tf":v["regime_tf"],"modifier":v["modifier"],
            "exposure":v["max_exposure"],"return_pct":round(v["return_pct"],5),
            "max_drawdown_pct":round(v["max_drawdown_pct"],5),
            "sim_trades":v["trades"],"start":v["started_at"],"last_bar":v["last_bar"],
            "regimes":regimes_by_id.get(v["experiment_id"],[]),
        } for v in usable],
        "paired_modifier_ablations":pairs,
    }


def enough_evidence(evidence):
    return (
        evidence["observed_experiment_count"] >= 6
        and any(
            sum(regime["bars"] for regime in row["regimes"]) >= MIN_OBSERVATION_BARS
            for row in evidence["variants"]
        )
    )


def analyst_instructions():
    return (
        "Du er forskningsanalytiker for PriceGauger Live-Sim Lab. Svar på norsk med "
        "fire tydelig nummererte seksjoner og én seksjon Usikkerhet: "
        "1) målte effekter av strategier/modifikatorer med matched controls; "
        "2) konkrete forbedringshypoteser for eksisterende funksjoner; "
        "3) presise forslag til nye strategier eller modifikatorer for Arkitekt, "
        "med falsifiserbar testprotokoll; 4) betinget teknisk regimekart: "
        "hva fungerte under HIGH_VOL, WHIPSAW, IMPULSE, TREND og RANGE. "
        "Tallene er fremoverrettede PAPER-simuleringer med omtrentlig kostnadsmodell "
        "og lab-native MACD-proxyer, IKKE Saxo-utfall og IKKE identiske Aen-strategier. "
        "Bruk eksperiment-ID ved konkrete påstander. Skill observasjon, hypotese og "
        "anbefalt test. Hvis regimedata eller handler er få, si eksplisitt at "
        "det ikke er nok belegg til en konklusjon. Mange varianter innebærer "
        "multiple testing og seleksjonsskjevhet. Ikke påstå signifikans uten "
        "grunnlag. Du har INGEN execution authority, og skal IKKE oppdatere "
        "strategier, modifikatorer, markedsregler eller risikorammer. "
        "Forslag er bare kandidater for fremtidige versjonerte forsøk."
    )


def _output_text(response_json):
    if isinstance(response_json.get("output_text"),str):
        return response_json["output_text"].strip()
    parts = []
    for msg in response_json.get("output",[]):
        for content in msg.get("content",[]):
            if content.get("type")=="output_text":
                parts.append(str(content.get("text") or ""))
    return "\n".join(parts).strip()


def request_analysis(evidence, *, api_key, model="gpt-5-mini", post=requests.post):
    response = post(
        RESPONSES_URL,
        headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"},
        json={"model":model,"store":False,"instructions":analyst_instructions(),
              "input":json.dumps(evidence,ensure_ascii=False)},
        timeout=90,
    )
    response.raise_for_status()
    answer = _output_text(response.json())
    if not answer:
        raise ValueError("AI response contained no text")
    return answer


def run_daily_analyst(report_date, *, db_path="pricegauger.db",
                      api_key=None, model=None, post=requests.post):
    """Exactly one attempted API analysis per day, recorded before remote call."""
    ensure_lab_schema(db_path)
    key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY","")
    if not key:
        return "NO_KEY"
    with connect(db_path) as db:
        row = db.execute("SELECT data_json FROM lsim_daily_reports WHERE report_date=?",
                         (report_date,)).fetchone()
    if row is None:
        return "NO_REPORT"
    payload = json.loads(row["data_json"])
    if payload.get("interpretation_status") != "PENDING_AI":
        return str(payload.get("interpretation_status"))
    variants, memory, _ = lab_snapshot(db_path=db_path)
    evidence = prepare_evidence(variants, memory)
    if not enough_evidence(evidence):
        return "TOO_EARLY"
    # Claim the daily API budget first, so process crashes/restarts do not
    # silently request many analyses on the same day.
    payload["interpretation_status"] = "AI_ATTEMPTED"
    payload["analysis_prompt_version"] = REPORT_PROMPT_VERSION
    with connect(db_path) as db:
        latest = db.execute(
            "SELECT data_json FROM lsim_daily_reports WHERE report_date=?",
            (report_date,)).fetchone()
        if latest is None or json.loads(latest["data_json"]).get("interpretation_status") != "PENDING_AI":
            return "ALREADY_ATTEMPTED"
        db.execute(
            "UPDATE lsim_daily_reports SET data_json=? WHERE report_date=?",
            (json.dumps(payload,ensure_ascii=False),report_date))
    try:
        answer = request_analysis(
            evidence,api_key=key,model=model or os.getenv("OPENAI_MARKET_MODEL","gpt-5-mini"),
            post=post)
    except Exception as exc:
        payload["interpretation_status"] = "AI_FAILED"
        payload["ai_error_type"] = type(exc).__name__
        with connect(db_path) as db:
            db.execute("UPDATE lsim_daily_reports SET data_json=? WHERE report_date=?",
                       (json.dumps(payload,ensure_ascii=False),report_date))
        return "AI_FAILED"
    payload["interpretation_status"] = "READY"
    payload["ai_interpretation"] = answer
    payload["analysis_evidence"] = {
        "candidate_count":len(evidence["variants"]),
        "paired_comparisons":len(evidence["paired_modifier_ablations"]),
        "prompt_version":REPORT_PROMPT_VERSION,
    }
    with connect(db_path) as db:
        db.execute("UPDATE lsim_daily_reports SET data_json=? WHERE report_date=?",
                   (json.dumps(payload,ensure_ascii=False),report_date))
    return "READY"
