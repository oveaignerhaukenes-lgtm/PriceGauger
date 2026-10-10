"""Independent Live-Sim Lab worker. Never imports broker or LIVE order paths."""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from database import connect
from live_sim_lab_analyst_v1 import run_daily_analyst
from live_sim_lab_store_v1 import process_lab_cycle, produce_daily_summary
from live_sim_lab_context_ablation_v1 import refresh_macro_schedule

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="pricegauger.db")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.interval < 15:
        parser.error("interval must be >= 15 seconds")
    LOGGER.info("Live-Sim Lab starting interval=%ds", args.interval)
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
