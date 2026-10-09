"""Independent Live-Sim Lab worker. Never imports broker or LIVE order paths."""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from live_sim_lab_store_v1 import process_lab_cycle, produce_daily_summary

LOGGER = logging.getLogger("pricegauger.live_sim_lab")


def run_once(*, db_path="pricegauger.db", now=None):
    moment = now or datetime.now(timezone.utc)
    evaluated = process_lab_cycle(db_path=db_path, now=moment)
    oslo = moment.astimezone(ZoneInfo("Europe/Oslo"))
    # A frozen factual evening snapshot, not an AI-generated interpretation.
    if oslo.hour >= 20:
        produce_daily_summary(oslo.date().isoformat(), db_path=db_path)
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
