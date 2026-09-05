from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
import time

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect, using_postgres
from spring_trade_engine.observers import observe_bars_v1
from spring_trade_engine.persistence import ensure_spring_schema_v1, persist_spring_observation_v1


LOGGER = logging.getLogger("pricegauger.spring_trade_engine")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceGauger Spring Trade Engine observer")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_SPRING_INTERVAL_SECONDS", "60")),
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=int(os.getenv("PRICEGAUGER_SPRING_WINDOW_MINUTES", "120")),
    )
    parser.add_argument(
        "--equilibrium-span",
        type=int,
        default=int(os.getenv("PRICEGAUGER_SPRING_EQUILIBRIUM_SPAN", "20")),
    )
    return parser


def _active_instruments() -> tuple[tuple[int, str], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT i.instrument_id, m.name AS market_name
            FROM pg_v2_collection_subscriptions c
            JOIN pg_v2_instruments i ON i.instrument_id = c.instrument_id AND i.active = TRUE
            JOIN pg_v2_markets m ON m.market_id = i.market_id AND m.active = TRUE
            WHERE c.enabled = TRUE
            ORDER BY i.instrument_id ASC
            """
        ).fetchall()
    return tuple((int(row["instrument_id"]), str(row["market_name"])) for row in rows)


def run_cycle(*, window_minutes: int, equilibrium_span: int) -> int:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=max(30, int(window_minutes)))
    store = CanonicalMarketBarStoreV2()
    persisted = 0

    for instrument_id, market_name in _active_instruments():
        try:
            bars = store.load_instrument_range(
                instrument_id=instrument_id,
                start=start,
                end=now,
                limit=max(500, int(window_minutes) + 30),
            )
            if len(bars) < 12:
                continue
            observation = observe_bars_v1(
                bars,
                equilibrium_span=equilibrium_span,
                minimum_bars=12,
            )
            persist_spring_observation_v1(observation)
            persisted += 1
            LOGGER.info(
                "spring observation market=%s instrument_id=%s observed_at=%s displacement_pct=%.5f velocity_pct_per_min=%.5f shock_score=%.3f energy_proxy=%.3f turning=%s",
                market_name,
                instrument_id,
                observation.observed_at.isoformat(),
                observation.displacement_pct,
                observation.velocity_pct_per_min,
                observation.shock_score,
                observation.energy_proxy,
                observation.turning_state,
            )
        except Exception as exc:
            LOGGER.warning(
                "spring observation failed market=%s instrument_id=%s error=%s",
                market_name,
                instrument_id,
                exc,
                exc_info=True,
            )
    return persisted


def main() -> None:
    if not using_postgres():
        raise SystemExit("Spring Trade Engine runtime requires PostgreSQL")
    args = _parser().parse_args()
    ensure_spring_schema_v1()
    interval = max(15, int(args.interval_seconds))
    LOGGER.info(
        "Spring Trade Engine observer started interval_seconds=%d window_minutes=%d equilibrium_span=%d observational_only=true",
        interval,
        max(30, int(args.window_minutes)),
        max(2, int(args.equilibrium_span)),
    )
    while True:
        cycle_started = time.monotonic()
        run_cycle(
            window_minutes=max(30, int(args.window_minutes)),
            equilibrium_span=max(2, int(args.equilibrium_span)),
        )
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, interval - elapsed))


if __name__ == "__main__":
    main()
