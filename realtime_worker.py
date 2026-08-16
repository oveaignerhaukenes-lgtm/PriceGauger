from __future__ import annotations

import argparse
import logging
import os
import threading
import time

from autotrader_macd_dry_run_v2 import run_macd_dry_run_forever_v2
from database import using_postgres
from live_technical_runtime_v2 import run_live_technical_forever_v2
from realtime_gap_repair import GapRepairingSaxoRealtimeService
from runtime_subscription_bridge_v2 import instrument_signature_v2, load_runtime_instruments_v2
from saxo_provider import SaxoInstrument, configured_instruments


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
    parser.add_argument(
        "--v2-registry-poll-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_V2_REGISTRY_POLL_SECONDS", "15")),
        help="Cadence for discovering enabled v2 collection subscriptions.",
    )
    parser.add_argument(
        "--autotrader-macd-dry-run-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_AUTOTRADER_MACD_DRY_RUN_SECONDS", "60")),
        help="Cadence for the read-only 30m MACD LONG/FLAT dry-run evaluator.",
    )
    return parser


def _start_v2_technical_runtime(
    *,
    instruments: dict[str, SaxoInstrument],
    db_path: str,
    interval_seconds: int,
) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("v2 TA-only live runtime disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_live_technical_forever_v2,
        kwargs={
            "instruments": instruments,
            "db_path": db_path,
            "interval_seconds": interval_seconds,
        },
        name="pricegauger-v2-ta-runtime",
        daemon=True,
    )
    thread.start()
    LOGGER.info("v2 TA-only live runtime started interval_seconds=%d", max(15, interval_seconds))
    return thread


def _start_autotrader_macd_dry_run(
    *,
    db_path: str,
    interval_seconds: int,
) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoTrader MACD dry-run disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_macd_dry_run_forever_v2,
        kwargs={
            "db_path": db_path,
            "interval_seconds": interval_seconds,
        },
        name="pricegauger-autotrader-macd-dry-run",
        daemon=True,
    )
    thread.start()
    LOGGER.info("AutoTrader MACD dry-run started interval_seconds=%d", max(30, interval_seconds))
    return thread


def _initial_runtime_instruments(
    configured: dict[str, SaxoInstrument],
) -> dict[str, SaxoInstrument]:
    if not using_postgres():
        return dict(configured)
    try:
        resolved = load_runtime_instruments_v2(configured)
    except Exception as exc:
        LOGGER.warning(
            "v2 collection registry unavailable at worker startup; using configured feed set: %s",
            exc,
            exc_info=True,
        )
        return dict(configured)
    LOGGER.info(
        "v2 collection registry loaded markets=%s",
        ",".join(resolved.registry_markets) or "none",
    )
    return resolved.instruments


def _watch_v2_registry(
    *,
    configured: dict[str, SaxoInstrument],
    runtime_instruments: dict[str, SaxoInstrument],
    restart_requested: threading.Event,
    poll_seconds: int,
) -> None:
    interval = max(5, int(poll_seconds))
    while True:
        time.sleep(interval)
        if not using_postgres():
            continue
        try:
            desired = load_runtime_instruments_v2(configured).instruments
        except Exception as exc:
            # Fail closed on an invalid/ambiguous registry without disturbing the
            # currently healthy stream generation. The next poll retries.
            LOGGER.warning("v2 collection registry refresh rejected: %s", exc, exc_info=True)
            continue
        if instrument_signature_v2(desired) == instrument_signature_v2(runtime_instruments):
            continue
        runtime_instruments.clear()
        runtime_instruments.update(desired)
        restart_requested.set()
        LOGGER.info(
            "v2 collection registry changed; requesting Saxo resubscribe markets=%s",
            ",".join(sorted(runtime_instruments)),
        )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parser().parse_args()

    configured = dict(configured_instruments())
    runtime_instruments = _initial_runtime_instruments(configured)
    restart_requested = threading.Event()

    _start_v2_technical_runtime(
        instruments=runtime_instruments,
        db_path=args.db,
        interval_seconds=args.v2_ta_interval_seconds,
    )
    _start_autotrader_macd_dry_run(
        db_path=args.db,
        interval_seconds=args.autotrader_macd_dry_run_seconds,
    )
    watcher = threading.Thread(
        target=_watch_v2_registry,
        kwargs={
            "configured": configured,
            "runtime_instruments": runtime_instruments,
            "restart_requested": restart_requested,
            "poll_seconds": args.v2_registry_poll_seconds,
        },
        name="pricegauger-v2-registry-watch",
        daemon=True,
    )
    watcher.start()

    while True:
        restart_requested.clear()
        service = GapRepairingSaxoRealtimeService(
            db_path=args.db,
            refresh_ms=args.refresh_ms,
            instruments=dict(runtime_instruments),
        )
        service.run_forever(stop_requested=restart_requested.is_set)
        if restart_requested.is_set():
            LOGGER.info("restarting Saxo stream to apply v2 collection subscription changes")
            continue
        break


if __name__ == "__main__":
    main()
