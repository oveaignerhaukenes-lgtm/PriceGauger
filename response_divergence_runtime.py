from __future__ import annotations

import logging
from pathlib import Path

from analysis_status import AnalysisStatusStore
from cross_market_state import CrossMarketStateSnapshot
from response_divergence import ResponseDivergenceSnapshot, refresh_response_divergences
from transmission_state_runtime import produce_transmission_states


LOGGER = logging.getLogger("pricegauger.response_divergence_runtime")


def produce_response_divergences(
    *,
    db_path: str | Path,
    cross_market: CrossMarketStateSnapshot | None = None,
    market: str = "Silver",
    status_store: AnalysisStatusStore | None = None,
) -> tuple[ResponseDivergenceSnapshot, ...]:
    """Refresh mature ResponseDivergence observations without affecting decisions.

    A cycle with no mature/aligned response window is a healthy no-op. Unexpected
    evaluation/storage failures are degraded locally and never stop the authoritative
    Information/Decision/forecast runtime. TransmissionState consumes only the
    successfully produced divergence observations from this stage.
    """
    status = status_store or AnalysisStatusStore(db_path)
    status.running(
        "response_divergence",
        "Kontrollerer modne markedsresponser mot tidligere Information State.",
    )
    try:
        snapshots = refresh_response_divergences(
            db_path,
            market=market,
            cross_market=cross_market,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status.failed("response_divergence", detail)
        status.skipped(
            "transmission_state",
            "TransmissionState hoppet over fordi ResponseDivergence-evalueringen feilet.",
        )
        LOGGER.exception("response-divergence refresh failed; analysis continues")
        return ()

    if not snapshots:
        status.complete(
            "response_divergence",
            "Ingen moden, temporalt gyldig markedsrespons å evaluere i denne syklusen.",
        )
        LOGGER.info("response-divergence refresh complete market=%s evaluations=0", market)
        produce_transmission_states(
            db_path=db_path,
            divergences=(),
            status_store=status,
        )
        return ()

    divergent = sum(item.status == "DIVERGENT" for item in snapshots)
    aligned = sum(item.status == "ALIGNED" for item in snapshots)
    unconfirmed = sum(item.status == "UNCONFIRMED" for item in snapshots)
    status.complete(
        "response_divergence",
        (
            f"{len(snapshots)} markedsrespons(er) evaluert: "
            f"{divergent} divergent, {aligned} aligned, {unconfirmed} ubekreftet."
        ),
    )
    LOGGER.info(
        "response-divergence refresh complete market=%s evaluations=%s divergent=%s aligned=%s unconfirmed=%s",
        market,
        len(snapshots),
        divergent,
        aligned,
        unconfirmed,
    )
    produce_transmission_states(
        db_path=db_path,
        divergences=snapshots,
        status_store=status,
    )
    return snapshots
