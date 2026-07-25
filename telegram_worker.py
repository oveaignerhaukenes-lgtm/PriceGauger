from __future__ import annotations

import argparse
import logging
import os
import time

from telegram_ingestion import fetch_search_plans_from_source
from telegram_sources import normalize_channels
from worker import DEFAULT_DB_PATH, DEFAULT_INTERVAL_SECONDS, run_once

LOGGER = logging.getLogger("pricegauger.telegram_worker")


def _plans_fetcher(*, channels: tuple[str, ...], mode: str):
    def fetcher(_legacy_channel: str, *, minimum_signal: int = 2):
        return fetch_search_plans_from_source(
            channels,
            mode=mode,
            minimum_signal=minimum_signal,
        )

    return fetcher


def run_source_once(
    *,
    channels: str | tuple[str, ...],
    mode: str = "web",
    db_path: str = DEFAULT_DB_PATH,
    minimum_signal: int = 2,
):
    normalized = normalize_channels(channels)
    return run_once(
        db_path=db_path,
        channel=normalized[0],
        minimum_signal=minimum_signal,
        plans_fetcher=_plans_fetcher(channels=normalized, mode=mode),
    )


def run_source_forever(
    *,
    channels: str | tuple[str, ...],
    mode: str = "web",
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    db_path: str = DEFAULT_DB_PATH,
    minimum_signal: int = 2,
) -> None:
    if interval_seconds < 30:
        raise ValueError("interval must be at least 30 seconds")
    normalized = normalize_channels(channels)
    LOGGER.info(
        "telegram worker started mode=%s channels=%s interval=%ss",
        mode,
        ",".join(normalized),
        interval_seconds,
    )
    while True:
        started = time.monotonic()
        try:
            run_source_once(
                channels=normalized,
                mode=mode,
                db_path=db_path,
                minimum_signal=minimum_signal,
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            LOGGER.exception("telegram source cycle failed; next cycle will retry")
        time.sleep(max(1.0, interval_seconds - (time.monotonic() - started)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configurable PriceGauger Telegram worker")
    parser.add_argument(
        "--channels",
        default=os.environ.get("TELEGRAM_CHANNELS", "Middle_East_Spectator"),
        help="Comma-separated @names or t.me links",
    )
    parser.add_argument(
        "--mode",
        choices=("web", "account"),
        default=os.environ.get("TELEGRAM_SOURCE_MODE", "web"),
        help="web needs no login; account uses Telethon and the user's session",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--minimum-signal", type=int, default=2)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.once:
        summary = run_source_once(
            channels=args.channels,
            mode=args.mode,
            db_path=args.db,
            minimum_signal=args.minimum_signal,
        )
        print(
            "TELEGRAM_WORKER_OK "
            f"mode={args.mode} fetched={summary.fetched} pending={summary.pending} "
            f"processed={summary.processed} bootstrap_skipped={summary.skipped_bootstrap}"
        )
        return
    run_source_forever(
        channels=args.channels,
        mode=args.mode,
        interval_seconds=args.interval,
        db_path=args.db,
        minimum_signal=args.minimum_signal,
    )


if __name__ == "__main__":
    main()
