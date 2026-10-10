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


def prepare_evidence(variants, regime_memory, *, selector_summary=None, trial_summary=None):
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
        "shadow_selectors":selector_summary or [],
        "perturbation_history":trial_summary or {},
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
        "evaluer selectorens kostede resultat mot faste kontroller og risikoen "
        "for å jage historiske vinnere. Bruk historikken over prøvde, "
        "pensjonerte og ventende perturbasjoner slik at du ikke foreslår "
        "å gjenta mislykkede forsøk uten ny falsifiserbar hypotese. "
        "Undersøk også makro/geopolitikk ablasjonen bare når fremoverrettet "
        "evidens faktisk finnes. Sammenlign samme kandidat mot BASE etter "
        "kostnader, rapporter datadekning, antall aktive hendelsesbarer, "
        "mistede trender og usikkerhet. Dersom alle fire armer er like og "
        "ingen kontekstsignaler er observert, kan ingen kontekstverdi "
        "tilskrives AI. Dette er risikofiltre, ikke retning eller makrooverraskelser. "
        "Du har INGEN execution authority, og skal IKKE oppdatere "
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
    # Evolving research inventory is evidence, not executable instructions.
    from live_sim_lab_evolution_v1 import evolution_snapshot
    selectors, trials, _ = evolution_snapshot(db_path=db_path)
    observed_selectors = [{
        "kind":s["selector_kind"],"nav_return_pct":round(
            (float(s.get("equity",10000.0))/10000.0-1)*100.0,5),
        "max_drawdown_pct":round(float(s.get("max_drawdown",0))*100,5),
        "switches":int(s.get("switches",0)),
        "current_experiment_id":s.get("selected_id"),
        "last_observation":s.get("last_bar"),
    } for s in selectors]
    retired=[{
        "id":t["experiment_id"],"config":t["config"],
        "outcome":t["outcome"]
    } for t in trials if t["status"]=="RETIRED"]
    queued=[{"id":t["experiment_id"],"config":t["config"],
              "parent":t.get("parent_id")}
            for t in trials if t["status"]=="QUEUED"]
    evidence = prepare_evidence(variants, memory,
        selector_summary=observed_selectors,
        trial_summary={
            "statuses":{status:sum(t["status"]==status for t in trials)
                        for status in ("RUNNING","QUEUED","RETIRED")},
            "recent_retired":retired[-12:],
            "next_untried":queued[:12],
        })
    # Evaluate exact paired four-arm context overlay evidence without asking the
    # model to hallucinate geopolitical news or infer nonexistent macro surprises.
    from live_sim_lab_context_ablation_v1 import context_ablation_snapshot
    _, context_arms, macro_health, _ = context_ablation_snapshot(db_path=db_path)
    by_parent = {}
    for item in context_arms:
        by_parent.setdefault(item["experiment_id"],{})[item["arm"]] = item
    comparisons = []
    for parent, runs in by_parent.items():
        control = runs.get("BASE")
        if not control or not int(control.get("bars",0)):
            continue
        row={"experiment_id":parent,"bars":int(control["bars"]),
             "macro_data_coverage_pct":round(
                 100*int(control.get("macro_known",0))/control["bars"],2),
             "geopolitical_data_coverage_pct":round(
                 100*int(control.get("geo_known",0))/control["bars"],2),
             "macro_trigger_bars":int(control.get("macro_triggered",0)),
             "geo_trigger_bars":int(control.get("geo_triggered",0)),
             "arms":[]}
        for kind, track in sorted(runs.items()):
            row["arms"].append({
                "name":kind,
                "nav_return_pct":round((float(track["equity"])/10000-1)*100,5),
                "delta_vs_base_pp":round(
                    (float(track["equity"])-float(control["equity"]))/100,5),
                "max_drawdown_pct":round(float(track["max_drawdown"])*100,5),
                "trades":int(track["trades"]),
            })
        comparisons.append(row)
    evidence["macro_geopolitical_ablation"]={
        "macro_calendar_status":macro_health["status"] if macro_health else "MISSING",
        "method":"prospective_same_parent_four_arm_next_open_with_cost",
        "pairs":comparisons,
    }
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
