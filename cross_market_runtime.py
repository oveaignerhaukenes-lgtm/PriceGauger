from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from analysis_status import AnalysisStatusStore
from cross_market_state import (
    RETURN_MARKETS,
    WINDOWS,
    YIELD_TENORS,
    CrossMarketStateSnapshot,
    CrossMarketStateStore,
    build_cross_market_state,
)
from response_divergence_runtime import produce_response_divergences


LOGGER = logging.getLogger("pricegauger.cross_market_runtime")


def produce_cross_market_state(
    *,
    db_path: str | Path,
    as_of: str | datetime | None = None,
    status_store: AnalysisStatusStore | None = None,
) -> CrossMarketStateSnapshot | None:
    """Build and persist one descriptive CrossMarketState snapshot.

    This producer is intentionally observational only. Missing/stale market data is
    represented inside the snapshot and does not make the worker cycle fail. Only
    unexpected producer/storage failures mark the stage FAILED.
    """
    status = status_store or AnalysisStatusStore(db_path)
    status.running(
        "cross_market_state",
        "Bygger synkronisert CrossMarketState fra canonical market history.",
    )
    try:
        snapshot = build_cross_market_state(path=db_path, market="Silver", as_of=as_of)
        CrossMarketStateStore(db_path).save(snapshot)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status.failed("cross_market_state", detail)
        LOGGER.exception("cross-market state production failed; analysis continues")
        return None

    observations = {item.name: item for item in snapshot.observations}
    fresh_markets = sum(
        observations[name].latest_observation_freshness == "FRESH"
        for name in RETURN_MARKETS
    )
    valid_windows = sum(
        observations[name].window_coverage[window] == "VALID"
        for name in RETURN_MARKETS
        for window in WINDOWS
    )
    missing_yields = sum(
        observations[name].latest_observation_freshness == "MISSING"
        for name in YIELD_TENORS
    )
    status.complete(
        "cross_market_state",
        (
            f"CrossMarketState lagret: {fresh_markets}/{len(RETURN_MARKETS)} ferske markeder, "
            f"{valid_windows}/{len(RETURN_MARKETS) * len(WINDOWS)} gyldige return-vinduer, "
            f"{missing_yields}/{len(YIELD_TENORS)} yield-serier mangler."
        ),
    )
    LOGGER.info(
        "cross-market snapshot persisted id=%s fresh_markets=%s valid_windows=%s missing_yields=%s",
        snapshot.snapshot_id,
        fresh_markets,
        valid_windows,
        missing_yields,
    )

    # ResponseDivergence consumes the just-persisted observation and prior persisted
    # Information State. This hook inherits CrossMarketState's placement before the
    # no-material-change early return, so response windows can mature on quiet-news
    # cycles without creating a parallel market-data path.
    produce_response_divergences(
        db_path=db_path,
        cross_market=snapshot,
        status_store=status,
    )
    return snapshot
