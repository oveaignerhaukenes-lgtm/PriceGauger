"""Independent Live-Sim Lab worker. Never imports broker or LIVE order paths."""
from __future__ import annotations

import argparse
import logging
import time
import threading
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from database import connect
from live_sim_lab_analyst_v1 import run_daily_analyst
from live_sim_lab_store_v1 import process_lab_cycle, produce_daily_summary
from live_sim_lab_context_ablation_v1 import refresh_macro_schedule
from live_sim_hyper_vigilant_v1 import process_hyper_cycle
from live_sim_ai_technical_trader_v1 import process_ai_paper_cycle

LOGGER = logging.getLogger("pricegauger.live_sim_lab")


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
        try:
            process_ai_paper_cycle(db_path=db_path)
        except Exception as exc:
            if started-last_error>=30.0:
                LOGGER.warning(
                    "AI Trader PAPER loop unavailable error_type=%s",
                    type(exc).__name__,
                )
                last_error=started
        stop_event.wait(max(0.1,interval-(time.monotonic()-started)))


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
    ai_thread=threading.Thread(
        target=run_ai_technical_research_loop,
        kwargs={"db_path":args.db,"stop_event":stop_event,"interval":5.0},
        name="pricegauger-ai-paper",
        daemon=True,
    )
    ai_thread.start()
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
