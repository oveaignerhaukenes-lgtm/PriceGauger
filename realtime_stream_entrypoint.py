from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import runpy
import sys

from database import using_postgres
from realtime_gap_repair import repair_closed_market_realtime_tail
from realtime_market_data import RealtimeMarketDataStore, minute_start, utc
from runtime_subscription_bridge_v2 import load_runtime_instruments_v2
from saxo_infoprice_probe import InfoPriceDiagnostic, fetch_infoprice_diagnostics
from saxo_provider import configured_client, configured_instruments


LOGGER = logging.getLogger("pricegauger.realtime_stream_preflight")


def _db_path_from_argv(argv: list[str]) -> str:
    for index, value in enumerate(argv):
        if value == "--db" and index + 1 < len(argv):
            return str(argv[index + 1])
        if value.startswith("--db="):
            return value.split("=", 1)[1]
    return os.getenv("PRICEGAUGER_DB_PATH", "pricegauger.db")


def _authoritative_closed_cutoff(item: InfoPriceDiagnostic) -> datetime | None:
    """Return Saxo's provider timestamp only when InfoPrice confirms market closed."""
    if item.is_market_open is not False or not item.last_updated:
        return None
    try:
        return minute_start(utc(item.last_updated))
    except (TypeError, ValueError):
        return None


def _runtime_instruments():
    configured = configured_instruments()
    if not using_postgres():
        return dict(configured)
    try:
        return dict(load_runtime_instruments_v2(configured).instruments)
    except Exception as exc:
        LOGGER.warning(
            "Closed-market preflight could not load v2 registry; using configured instruments: %s",
            exc,
        )
        return dict(configured)


def run_closed_market_preflight(*, db_path: str) -> int:
    """Repair impossible quote-built tails using direct Saxo InfoPrice truth.

    This deliberately queries one exact product at a time so one unavailable product
    cannot prevent repair of the rest. No order/trading endpoint is used.
    """
    client = configured_client()
    instruments = _runtime_instruments()
    store = RealtimeMarketDataStore(db_path)
    total_removed = 0

    for market, instrument in instruments.items():
        try:
            rows = fetch_infoprice_diagnostics(
                client=client,
                instruments={market: instrument},
            )
        except Exception as exc:
            LOGGER.warning(
                "Closed-market InfoPrice preflight skipped market=%s uic=%s: %s",
                market,
                instrument.uic,
                exc,
            )
            continue
        if not rows:
            continue
        item = rows[0]
        cutoff = _authoritative_closed_cutoff(item)
        if cutoff is None:
            LOGGER.info(
                "Closed-market preflight no repair market=%s uic=%s market_open=%s last_updated=%s",
                market,
                instrument.uic,
                item.is_market_open,
                item.last_updated,
            )
            continue
        removed = repair_closed_market_realtime_tail(
            store=store,
            market=market,
            instrument=instrument,
            cutoff=cutoff,
        )
        total_removed += removed
        LOGGER.warning(
            "Closed-market InfoPrice repair market=%s uic=%s cutoff=%s removed_rows=%d price_type_bid=%s price_type_ask=%s",
            market,
            instrument.uic,
            cutoff.isoformat(),
            removed,
            item.price_type_bid,
            item.price_type_ask,
        )
    return total_removed


def main() -> None:
    worker_args = list(sys.argv[1:])
    db_path = _db_path_from_argv(worker_args)
    try:
        removed = run_closed_market_preflight(db_path=db_path)
        LOGGER.info("Closed-market InfoPrice preflight complete removed_rows=%d", removed)
    except Exception as exc:
        # Feed-quality repair must never prevent the stream process from starting.
        LOGGER.warning("Closed-market InfoPrice preflight failed open: %s", exc, exc_info=True)

    target = Path(__file__).with_name("realtime_worker.py")
    sys.argv = [str(target), *worker_args]
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
