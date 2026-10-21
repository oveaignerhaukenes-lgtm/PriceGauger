"""Independent Live-Sim Lab worker. Never imports broker or LIVE order paths."""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from database import connect
from live_sim_lab_analyst_v1 import run_daily_analyst
from live_sim_lab_store_v1 import process_lab_cycle, produce_daily_summary
from live_sim_lab_context_ablation_v1 import refresh_macro_schedule
from live_sim_hyper_vigilant_v1 import process_hyper_cycle
from live_sim_hyper_chase_10s_v1 import process_chase_cycle_v1
from live_sim_ai_technical_trader_v1 import process_ai_paper_cycle
from live_sim_ai_technical_status_v1 import record_ai_heartbeat
from live_sim_lab_ai_context_reviewer_v1 import review_selected_pairs

LOGGER = logging.getLogger("pricegauger.live_sim_lab")

# A one-time read-only performance audit per LAB worker boot.
# Emit only research-paper metrics and configuration labels, never account data.
_SIM_AUDIT_EMITTED = False
_AEN_HEALTH_LAST = None
_TECH100_REGIME_STUDY_EMITTED = False


def emit_sim_performance_audit_v1(*, db_path="pricegauger.db"):
    """Print factual, forward-only SIM ledger snapshots to project owner logs.

    This does not create SIM history, alter strategies, or touch Saxo/LIVE.
    Results from different starting dates or fill/cost models MUST NOT be
    interpreted as a head-to-head profitability ranking.
    """
    from live_sim_lab_store_v1 import lab_snapshot
    experiments, regimes, feeds = lab_snapshot(db_path=db_path)
    LOGGER.info("SIM_AUDIT_META %s", json.dumps({
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "variants": len(experiments), "feeds": feeds,
        "regime_rows": len(regimes),
        "note": "research-only: normalized NAV; 5bps turnover; no Saxo fills or funding",
    }, default=str, separators=(",", ":"), ensure_ascii=False))
    for row in experiments:
        # Keep the complete cohort, not only winners: prevents cherry-picking.
        fields=("experiment_id","market_name","family","signal_tf","regime_tf",
                "modifier","max_exposure","started_at","status","observed_bars",
                "last_bar","return_pct","max_drawdown_pct","trades",
                "above_start_pct","positive_bar_pct","exposure")
        LOGGER.info("SIM_AUDIT_VARIANT %s",json.dumps(
            {k:row.get(k) for k in fields},separators=(",",":"),ensure_ascii=False,default=str))
    # Each optional family is logged separately, because a paper 1s bid/ask
    # strategy is not directly comparable with a 1m next-bar open strategy.
    modules=(
        ("HYPER","live_sim_hyper_vigilant_v1","hyper_snapshot",1),
        ("CHASE10","live_sim_hyper_chase_10s_v1","chase_snapshot_v1",0),
        ("SELECTOR","live_sim_lab_evolution_v1","evolution_snapshot",0),
        ("WHIP","live_sim_lab_whipsaw_ablation_v1","whipsaw_snapshot",1),
        ("CONTEXT","live_sim_lab_context_ablation_v1","context_ablation_snapshot",1),
        ("AI_PAIR","live_sim_lab_ai_context_pairs_v1","pair_snapshot",1),
        ("AI_TECH","live_sim_ai_technical_trader_v1","ai_technical_snapshot",0),
    )
    from importlib import import_module
    for label,module,method,index in modules:
        try:
            result=getattr(import_module(module),method)(db_path=db_path)
            rows=result[index]
            LOGGER.info("SIM_AUDIT_GROUP group=%s rows=%d",label,len(rows))
            for row in rows:
                # Curate numeric evidence without dumping model prompts,
                # generated news or raw source/provider data into logs.
                fields=("provider_uic","market_name","experiment_id","trial_id",
                        "arm","selector_kind","selected_id","equity","return_pct",
                        "max_drawdown","trades","ticks","bars","last_bar",
                        "started_at","updated_at","first_bar","last_quote",
                        "spread_cost_nok","fees_nok","costs","transaction_cost_nok",
                        "raw_whipsaw_bars","effective_whipsaw_bars","blocked_increases",
                        "forced_reductions","forced_flats","macro_known","geo_known",
                        "macro_triggered","geo_triggered","model_status","switches")
                LOGGER.info("SIM_AUDIT_%s %s",label,json.dumps(
                    {k:row.get(k) for k in fields if k in row},
                    separators=(",",":"),ensure_ascii=False,default=str))
        except Exception as exc:
            LOGGER.warning("SIM_AUDIT_GROUP_FAILED group=%s error_type=%s",label,type(exc).__name__)



def run_once(*, db_path="pricegauger.db", now=None):
    moment = now or datetime.now(timezone.utc)
    # A bounded, at-most-12-hour official calendar refresh. Failures are
    # evidence gaps, not execution failures or a reason to stop paper sampling.
    try:
        macro_state = refresh_macro_schedule(db_path=db_path, now=moment)
        if macro_state not in ("UNCHANGED",):
            LOGGER.info("Context Lab macro calendar state=%s",macro_state)
    except Exception as exc:
        LOGGER.warning("Context Lab calendar unavailable error_type=%s",
                       type(exc).__name__)
    evaluated = process_lab_cycle(db_path=db_path, now=moment)
    # AEn has NO Saxo imports or broker authority. 5 frozen 0.01-unit
    # PAPER cohorts enrol prospectively on the next minute boundary.
    # Its failure must not interrupt the existing research ecosystem.
    try:
        from aen_forward_paper_v1 import process_forward_cycle
        settled=process_forward_cycle(db_path=db_path,now=moment)
        if settled:
            LOGGER.info("AEn forward PAPER settled cohorts=%d",settled)
        # The main SIM logger is explicitly visible on Railway, unlike
        # submodule INFO loggers on installations with restrictive levels.
        global _AEN_HEALTH_LAST
        if _AEN_HEALTH_LAST is None or moment-_AEN_HEALTH_LAST>=timedelta(minutes=5):
            from aen_forward_paper_v1 import forward_health_snapshot
            LOGGER.info("AEN_FORWARD_HEALTH %s",json.dumps(
                forward_health_snapshot(db_path=db_path),
                separators=(",",":"),default=str))
            _AEN_HEALTH_LAST=moment
    except Exception as exc:
        LOGGER.warning("AEn forward PAPER unavailable error_type=%s",type(exc).__name__)
    # One-off bounded Tech100 regime research for the operator. Research-only;
    # no Saxo client, strategy registration, LIVE config or database writes.
    global _TECH100_REGIME_STUDY_EMITTED
    if not _TECH100_REGIME_STUDY_EMITTED:
        try:
            from tech100_regime_forensics_20261016 import emit_tech100_regime_study
            _TECH100_REGIME_STUDY_EMITTED = bool(emit_tech100_regime_study(
                LOGGER, db_path=db_path, now=moment
            ))
        except Exception as exc:
            LOGGER.warning("REGIME_STUDY_FAILED error_type=%s", type(exc).__name__)
    global _SIM_AUDIT_EMITTED
    if not _SIM_AUDIT_EMITTED:
        try:
            emit_sim_performance_audit_v1(db_path=db_path)
            _SIM_AUDIT_EMITTED = True
        except Exception as exc:
            LOGGER.warning("SIM_AUDIT_FAILED error_type=%s",type(exc).__name__)
    oslo = moment.astimezone(ZoneInfo("Europe/Oslo"))
    # A frozen factual evening snapshot, not an AI-generated interpretation.
    if oslo.hour >= 20:
        date = oslo.date().isoformat()
        with connect(db_path) as db:
            existing = db.execute(
                "SELECT 1 FROM lsim_daily_reports WHERE report_date=?", (date,)
            ).fetchone()
        if existing is None:
            produce_daily_summary(date, db_path=db_path)
        result = run_daily_analyst(date, db_path=db_path)
        if result == "READY":
            LOGGER.info("Live-Sim Lab daily four-task AI report ready date=%s", date)
    return evaluated


def run_hyper_one_second_loop(*,db_path="pricegauger.db",stop_event,interval=1.0):
    """Independent research thread: only durable quote readers/writers.

    No Saxo client, trading runtime, strategy arming, or broker API access.
    Standard 1m Lab and the 12h macro refresh retain their 60s schedule.
    """
    LOGGER.info("Hyper-Vigilant Stochastic PAPER loop started poll=%.1fs",interval)
    last_error=0.0
    while not stop_event.is_set():
        started=time.monotonic()
        try:
            process_hyper_cycle(db_path=db_path)
        except Exception as exc:
            # Under DB failure, keep the loop responsive without log flooding.
            if started-last_error>=30.0:
                LOGGER.warning(
                    "Hyper-Vigilant Stochastic PAPER cycle unavailable "
                    "error_type=%s",type(exc).__name__,
                )
                last_error=started
        # Independent, purely quote-based hyper-chase counterfactual arms.
        # Failure of either PAPER engine must not stall the other.
        try:
            process_chase_cycle_v1(db_path=db_path)
        except Exception as exc:
            if started-last_error>=30.0:
                LOGGER.warning(
                    "HyperVigilant Chase 10s PAPER cycle unavailable error_type=%s",
                    type(exc).__name__,
                )
                last_error=started
        stop_event.wait(max(0.1,interval-(time.monotonic()-started)))


def run_ai_technical_research_loop(*,db_path="pricegauger.db",stop_event,interval=5.0):
    """Independent event-driven LLM PAPER researcher, no order execution.

    Reviews on 3m cadence, or sustained loss >60s, max 80 calls/day and
    >=90s between requests. A slow API cannot stall 1s Hyper Stochastic.
    """
    LOGGER.info(
        "AI Trader PAPER technical-only loop started poll=%.1fs",
        interval,
    )
    last_error=0.0
    while not stop_event.is_set():
        started=time.monotonic()
        status="OK"
        error_type=""
        try:
            process_ai_paper_cycle(db_path=db_path)
        except Exception as exc:
            status="ERROR"
            error_type=type(exc).__name__
            if started-last_error>=30.0:
                LOGGER.warning(
                    "AI Trader PAPER loop unavailable error_type=%s",
                    error_type,
                )
                last_error=started
        # Separate worker-side proof of liveness; model key availability is
        # measured here, not guessed from the public web app's environment.
        try:
            import os
            record_ai_heartbeat(
                db_path=db_path,key_configured=bool(os.getenv("OPENAI_API_KEY")),
                result=status,error_type=error_type,
            )
        except Exception as exc:
            if started-last_error>=30.0:
                LOGGER.warning("AI Trader heartbeat write unavailable error_type=%s",
                               type(exc).__name__)
                last_error=started
        stop_event.wait(max(0.1,interval-(time.monotonic()-started)))


def run_ai_context_pair_loop(*,db_path="pricegauger.db",stop_event,interval=60.0):
    """Source-verified contextual AI review, research-only and rate-bounded.

    Never blocks the main 60s LAB settlement or the 1s Hyper stream.
    """
    LOGGER.info("AI context paired PAPER reviewer started poll=%.1fs",interval)
    last_error=0.0
    while not stop_event.is_set():
        started=time.monotonic()
        try:
            done=review_selected_pairs(db_path=db_path)
            if done:
                LOGGER.info("AI context pair reviews requested=%d",done)
        except Exception as exc:
            if started-last_error>=60:
                LOGGER.warning("AI context pair reviewer unavailable error_type=%s",
                               type(exc).__name__)
                last_error=started
        stop_event.wait(max(0.1,interval-(time.monotonic()-started)))


def optional_paper_ai_enabled(variable: str) -> bool:
    """All legacy LLM PAPER loops opt in individually, not by presence of API key."""
    if variable not in {"PRICEGAUGER_LAB_AI_TECH_ENABLED", "PRICEGAUGER_LAB_AI_PAIRS_ENABLED"}:
        raise ValueError("Unknown PAPER AI feature gate")
    return os.getenv(variable, "0").strip().lower() in ("1", "true", "yes", "on")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="pricegauger.db")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.interval < 15:
        parser.error("interval must be >= 15 seconds")
    LOGGER.info("Live-Sim Lab starting interval=%ds", args.interval)
    stop_event=threading.Event()
    hyper_thread=threading.Thread(
        target=run_hyper_one_second_loop,
        kwargs={"db_path":args.db,"stop_event":stop_event,"interval":1.0},
        name="pricegauger-hyper-paper",
        daemon=True,
    )
    hyper_thread.start()
    # Costly AI PAPER experiments are explicit opt-ins. This does not affect
    # historical simulator, 1s HyperChase PAPER, or any V3 LIVE AI modifier.
    if optional_paper_ai_enabled("PRICEGAUGER_LAB_AI_TECH_ENABLED"):
        ai_thread=threading.Thread(
            target=run_ai_technical_research_loop,
            kwargs={"db_path":args.db,"stop_event":stop_event,"interval":5.0},
            name="pricegauger-ai-paper",daemon=True,
        )
        ai_thread.start()
    else:
        LOGGER.info("AI technical PAPER LLM loop disabled; opt in PRICEGAUGER_LAB_AI_TECH_ENABLED=1")
    if optional_paper_ai_enabled("PRICEGAUGER_LAB_AI_PAIRS_ENABLED"):
        pair_thread=threading.Thread(
            target=run_ai_context_pair_loop,
            kwargs={"db_path":args.db,"stop_event":stop_event,"interval":60.0},
            name="pricegauger-ai-context-paper",daemon=True,
        )
        pair_thread.start()
    else:
        LOGGER.info("AI context-pair PAPER LLM loop disabled; opt in PRICEGAUGER_LAB_AI_PAIRS_ENABLED=1")
    while True:
        started = time.monotonic()
        try:
            count = run_once(db_path=args.db)
            if count:
                LOGGER.info("Lab ingested %d new shared market bars", count)
        except Exception:
            LOGGER.exception("Lab cycle failed; other services remain unaffected")
        time.sleep(max(1.0, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
