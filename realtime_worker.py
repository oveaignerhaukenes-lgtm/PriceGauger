from __future__ import annotations

import argparse
import logging
import os
import threading

from database import using_postgres
from live_technical_runtime_v2 import run_live_technical_forever_v2
from realtime_gap_repair import GapRepairingSaxoRealtimeService


LOGGER = logging.getLogger("pricegauger.realtime_worker")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceGauger Saxo realtime stream worker")
    parser.add_argument("--db", default=os.getenv("PRICEGAUGER_DB_PATH", "pricegauger.db"))
    parser.add_argument(
        "--refresh-ms",
        type=int,
        default=int(os.getenv("PRICEGAUGER_STREAM_REFRESH_MS", "1000")),
        help="Requested Saxo subscription refresh rate in milliseconds.",
    )
    parser.add_argument(
        "--v2-ta-interval-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_V2_TA_INTERVAL_SECONDS", "60")),
        help="Refresh cadence for persisted TA-only v2 state on PostgreSQL.",
    )
    return parser


def _start_v2_technical_runtime(
    *,
    service: GapRepairingSaxoRealtimeService,
    db_path: str,
    interval_seconds: int,
) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("v2 TA-only live runtime disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_live_technical_forever_v2,
        kwargs={
            "instruments": service.instruments,
            "db_path": db_path,
            "interval_seconds": interval_seconds,
        },
        name="pricegauger-v2-ta-runtime",
        daemon=True,
    )
    thread.start()
    LOGGER.info("v2 TA-only live runtime started interval_seconds=%d", max(15, interval_seconds))
    return thread


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parser().parse_args()
    service = GapRepairingSaxoRealtimeService(db_path=args.db, refresh_ms=args.refresh_ms)
    _start_v2_technical_runtime(
        service=service,
        db_path=args.db,
        interval_seconds=args.v2_ta_interval_seconds,
    )
    service.run_forever()


if __name__ == "__main__":
    main()
