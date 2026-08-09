from __future__ import annotations

import argparse
import logging
import os

from saxo_streaming import SaxoRealtimeService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceGauger Saxo realtime stream worker")
    parser.add_argument("--db", default=os.getenv("PRICEGAUGER_DB_PATH", "pricegauger.db"))
    parser.add_argument(
        "--refresh-ms",
        type=int,
        default=int(os.getenv("PRICEGAUGER_STREAM_REFRESH_MS", "1000")),
        help="Requested Saxo subscription refresh rate in milliseconds.",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parser().parse_args()
    service = SaxoRealtimeService(db_path=args.db, refresh_ms=args.refresh_ms)
    service.run_forever()


if __name__ == "__main__":
    main()
