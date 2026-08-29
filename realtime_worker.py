from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time

from autotrader_automanage_runtime_v2 import run_automanage_strategy_forever_v2
from autotrader_closed_position_reconciliation_v2 import (
    run_closed_position_equity_reconciliation_forever_v2,
)
from autotrader_live_close_v1 import run_live_close_forever_v1
from autotrader_macd_dry_run_v2 import run_macd_dry_run_forever_v2
from autotrader_risk_control_v2 import (
    run_managed_risk_reaction_forever_v2,
    run_risk_control_forever_v2,
)
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_live_close_v2 import run_strategy_live_close_forever_v2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import using_postgres
from live_technical_runtime_v2 import run_live_technical_forever_v2
from market_history_store import MarketHistoryStore
from realtime_gap_repair import GapRepairingSaxoRealtimeService
from runtime_subscription_bridge_v2 import instrument_signature_v2, load_runtime_instruments_v2
from saxo_chart_live import FormingCandleStore
from saxo_infoprice_probe import run_infoprice_probe_forever
from saxo_provider import SaxoInstrument, configured_instruments


LOGGER = logging.getLogger("pricegauger.realtime_worker")
FRESHNESS_PROBE_SECONDS = 60


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
    parser.add_argument(
        "--autotrader-strategy-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_AUTOTRADER_STRATEGY_SECONDS", "15")),
        help="Cadence for active LIVE AutoManage strategy planning. Closed 30m bars remain the signal clock.",
    )
    parser.add_argument(
        "--autotrader-risk-control-seconds",
        "--autotrader-risk-dry-run-seconds",
        dest="autotrader_risk_control_seconds",
        type=int,
        default=int(
            os.getenv(
                "PRICEGAUGER_AUTOTRADER_RISK_CONTROL_SECONDS",
                os.getenv("PRICEGAUGER_AUTOTRADER_RISK_DRY_RUN_SECONDS", "10"),
            )
        ),
        help="Cadence for the open-position RiskControl evaluator.",
    )
    parser.add_argument(
        "--autotrader-managed-risk-reaction-seconds",
        type=int,
        default=int(
            os.getenv("PRICEGAUGER_AUTOTRADER_MANAGED_RISK_REACTION_SECONDS", "2")
        ),
        help="Fast cadence for exact Auto-managed position risk reaction only.",
    )
    parser.add_argument(
        "--autotrader-live-close-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_AUTOTRADER_LIVE_CLOSE_SECONDS", "2")),
        help="Cadence for the guarded LIVE close-only executor. No Saxo calls occur while disarmed.",
    )
    parser.add_argument(
        "--autotrader-strategy-live-close-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_AUTOTRADER_STRATEGY_LIVE_CLOSE_SECONDS", "2")),
        help="Cadence for consuming strategy CLOSE requests through the hardened LIVE close gate.",
    )
    parser.add_argument(
        "--autotrader-equity-reconciliation-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_AUTOTRADER_EQUITY_RECONCILIATION_SECONDS", "5")),
        help="Cadence for authoritative Saxo closed-position P/L booking.",
    )
    parser.add_argument(
        "--saxo-infoprice-probe-seconds",
        type=int,
        default=int(os.getenv("PRICEGAUGER_SAXO_INFOPRICE_PROBE_SECONDS", "300")),
        help="Diagnostic cadence for Saxo InfoPrice feed-quality inspection.",
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


def _start_autotrader_strategy(*, db_path: str, interval_seconds: int) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoManage strategy runtime disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_automanage_strategy_forever_v2,
        kwargs={"db_path": db_path, "interval_seconds": interval_seconds},
        name="pricegauger-autotrader-strategy-runtime",
        daemon=True,
    )
    thread.start()
    LOGGER.info(
        "AutoManage strategy runtime started interval_seconds=%d; signals remain closed-30m only",
        max(5, interval_seconds),
    )
    return thread


def _start_autotrader_risk_control(*, interval_seconds: int) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoTrader RiskControl disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_risk_control_forever_v2,
        kwargs={"interval_seconds": interval_seconds},
        name="pricegauger-autotrader-risk-control",
        daemon=True,
    )
    thread.start()
    LOGGER.info("AutoTrader RiskControl started interval_seconds=%d", max(5, interval_seconds))
    return thread


def _start_autotrader_managed_risk_reaction(
    *,
    interval_seconds: int,
) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoTrader managed risk reaction disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_managed_risk_reaction_forever_v2,
        kwargs={"interval_seconds": interval_seconds},
        name="pricegauger-autotrader-managed-risk-reaction",
        daemon=True,
    )
    thread.start()
    LOGGER.info(
        "AutoTrader managed risk reaction started interval_seconds=%d",
        max(1, interval_seconds),
    )
    return thread


def _start_autotrader_live_close(*, interval_seconds: int) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoTrader LIVE close-only disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_live_close_forever_v1,
        kwargs={"interval_seconds": interval_seconds},
        name="pricegauger-autotrader-live-close",
        daemon=True,
    )
    thread.start()
    LOGGER.info(
        "AutoTrader LIVE close-only runtime started interval_seconds=%d; execution remains two-key gated",
        max(1, interval_seconds),
    )
    return thread


def _start_autotrader_strategy_live_close(*, interval_seconds: int) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoManage strategy LIVE close bridge disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_strategy_live_close_forever_v2,
        kwargs={"interval_seconds": interval_seconds},
        name="pricegauger-autotrader-strategy-live-close",
        daemon=True,
    )
    thread.start()
    LOGGER.info(
        "AutoManage strategy LIVE close bridge started interval_seconds=%d; global close gate still authoritative",
        max(1, interval_seconds),
    )
    return thread


def _start_autotrader_equity_reconciliation(*, interval_seconds: int) -> threading.Thread | None:
    if not using_postgres():
        LOGGER.info("AutoTrader equity reconciliation disabled: PostgreSQL is not configured")
        return None
    thread = threading.Thread(
        target=run_closed_position_equity_reconciliation_forever_v2,
        kwargs={"interval_seconds": interval_seconds},
        name="pricegauger-autotrader-equity-reconciliation",
        daemon=True,
    )
    thread.start()
    LOGGER.info(
        "AutoTrader authoritative P/L reconciliation started interval_seconds=%d",
        max(2, interval_seconds),
    )
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


def _run_freshness_probe(
    *,
    service: GapRepairingSaxoRealtimeService,
    markets: tuple[str, ...],
    db_path: str,
    stop_requested,
) -> None:
    """Log live-price, chart-stream, canonical and history boundaries together."""
    canonical = CanonicalMarketBarStoreV2(db_path)
    history = MarketHistoryStore(db_path)
    chart_store = FormingCandleStore(db_path)
    while not stop_requested():
        try:
            statuses = {item.market: item for item in service.store.load_statuses()}
            chart_statuses = {item.market: item for item in chart_store.load_statuses()}
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=2)
            for market in markets:
                status = statuses.get(market)
                chart_status = chart_statuses.get(market)
                latest_bar = canonical.load_latest(market=market) if using_postgres() else None
                points = history.load_range(market=market, start=start, end=now, limit=5000)
                history_latest = points[-1][0] if points else None
                LOGGER.info(
                    "realtime freshness probe market=%s stream_state=%s last_quote_at=%s chart_state=%s chart_last_event_at=%s chart_last_candle_at=%s chart_delay_minutes=%s chart_actual_refresh_ms=%s canonical_bar_at=%s history_latest_at=%s",
                    market,
                    None if status is None else status.state,
                    None if status is None else status.last_quote_at,
                    None if chart_status is None else chart_status.state,
                    None if chart_status is None else chart_status.last_event_at,
                    None if chart_status is None else chart_status.last_candle_at,
                    None if chart_status is None else chart_status.delayed_by_minutes,
                    None if chart_status is None else chart_status.actual_refresh_ms,
                    None if latest_bar is None else latest_bar.bar_time,
                    history_latest,
                )
        except Exception as exc:
            LOGGER.warning("realtime freshness probe failed: %s", exc, exc_info=True)
        for _ in range(FRESHNESS_PROBE_SECONDS):
            if stop_requested():
                return
            time.sleep(1)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parser().parse_args()

    if using_postgres():
        ensure_autotrader_schema_v2()

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
    _start_autotrader_strategy(
        db_path=args.db,
        interval_seconds=args.autotrader_strategy_seconds,
    )
    _start_autotrader_risk_control(
        interval_seconds=args.autotrader_risk_control_seconds,
    )
    _start_autotrader_managed_risk_reaction(
        interval_seconds=args.autotrader_managed_risk_reaction_seconds,
    )
    _start_autotrader_live_close(
        interval_seconds=args.autotrader_live_close_seconds,
    )
    _start_autotrader_strategy_live_close(
        interval_seconds=args.autotrader_strategy_live_close_seconds,
    )
    _start_autotrader_equity_reconciliation(
        interval_seconds=args.autotrader_equity_reconciliation_seconds,
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
        probe = threading.Thread(
            target=_run_freshness_probe,
            kwargs={
                "service": service,
                "markets": tuple(sorted(runtime_instruments)),
                "db_path": args.db,
                "stop_requested": restart_requested.is_set,
            },
            name="pricegauger-realtime-freshness-probe",
            daemon=True,
        )
        probe.start()
        if service.client is not None:
            infoprice_probe = threading.Thread(
                target=run_infoprice_probe_forever,
                kwargs={
                    "client": service.client,
                    "instruments": service.instruments,
                    "stop_requested": restart_requested.is_set,
                    "interval_seconds": args.saxo_infoprice_probe_seconds,
                },
                name="pricegauger-saxo-infoprice-probe",
                daemon=True,
            )
            infoprice_probe.start()
        service.run_forever(stop_requested=restart_requested.is_set)
        if restart_requested.is_set():
            LOGGER.info("restarting Saxo stream to apply v2 collection subscription changes")
            continue
        break


if __name__ == "__main__":
    main()
