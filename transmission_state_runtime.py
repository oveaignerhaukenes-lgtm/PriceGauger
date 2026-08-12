from __future__ import annotations

import logging
from pathlib import Path

from analysis_status import AnalysisStatusStore
from response_divergence import ResponseDivergenceSnapshot
from transmission_state import TransmissionStateSnapshot, TransmissionStateStore, build_transmission_state


LOGGER = logging.getLogger("pricegauger.transmission_state_runtime")


def produce_transmission_states(
    *,
    db_path: str | Path,
    divergences: tuple[ResponseDivergenceSnapshot, ...],
    status_store: AnalysisStatusStore | None = None,
) -> tuple[TransmissionStateSnapshot, ...]:
    """Build TransmissionState from newly evaluated ResponseDivergence snapshots.

    The stage is descriptive only. No input snapshots is a healthy no-op. Unexpected
    classification/storage failures are degraded locally and do not affect Decision
    State, forecasts, notifications, or trading.
    """
    status = status_store or AnalysisStatusStore(db_path)
    status.running(
        "transmission_state",
        "Vurderer observerte transmisjonsmønstre bak modne markedsresponser.",
    )

    if not divergences:
        status.complete(
            "transmission_state",
            "Ingen nye modne ResponseDivergence-observasjoner å klassifisere i denne syklusen.",
        )
        LOGGER.info("transmission-state refresh complete evaluations=0")
        return ()

    try:
        snapshots = tuple(build_transmission_state(item) for item in divergences)
        TransmissionStateStore(db_path).save_all(snapshots)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        status.failed("transmission_state", detail)
        LOGGER.exception("transmission-state production failed; analysis continues")
        return ()

    resolved = sum(item.resolution_status == "RESOLVED" for item in snapshots)
    unresolved = len(snapshots) - resolved
    channels: dict[str, int] = {}
    for item in snapshots:
        if item.dominant_channel is not None:
            channels[item.dominant_channel] = channels.get(item.dominant_channel, 0) + 1
    channel_detail = ""
    if channels:
        channel_detail = " Dominerende mønstre: " + ", ".join(
            f"{name}={count}" for name, count in sorted(channels.items())
        ) + "."
    status.complete(
        "transmission_state",
        f"{len(snapshots)} transmisjonsstate(r) lagret: {resolved} resolved, {unresolved} unresolved.{channel_detail}",
    )
    LOGGER.info(
        "transmission-state refresh complete evaluations=%s resolved=%s unresolved=%s channels=%s",
        len(snapshots),
        resolved,
        unresolved,
        channels,
    )
    return snapshots
