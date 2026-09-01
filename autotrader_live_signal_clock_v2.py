from __future__ import annotations

from typing import Iterable

from autotrader_intrabar30_shadow_v2 import intrabar_macd_samples_v2
from autotrader_macd_dry_run_v2 import (
    MacdObservationV2,
    closed_30m_bars_v2,
    macd_observations_v2,
)
from autotrader_strategy_catalog_v2 import INTRABAR_30M_LONG_FLAT_STRATEGY_V2


SIGNAL_CLOCK_CLOSED_30M = "CLOSED_30M"
SIGNAL_CLOCK_INTRABAR_30M_1M = "INTRABAR_30M_1M"


def automanage_signal_clock_v2(strategy_key: str) -> str:
    if str(strategy_key) == INTRABAR_30M_LONG_FLAT_STRATEGY_V2:
        return SIGNAL_CLOCK_INTRABAR_30M_1M
    return SIGNAL_CLOCK_CLOSED_30M


def automanage_signal_pair_v2(
    *,
    strategy_key: str,
    points: Iterable[tuple[str, float]],
    market: str,
) -> tuple[MacdObservationV2, MacdObservationV2]:
    """Return the latest two replayable MACD samples for one LIVE strategy.

    Classic strategies consume only fully closed 30m bars. The intrabar strategy
    keeps MACD parameters at 12/26/9 on a 30m construction, but samples the forming
    30m close after every fully observed canonical 1m bar. Both clocks are converted
    to the same ``MacdObservationV2`` contract before downstream position planning.

    No historical execution authority is created here. Restart/bootstrap replay
    policy remains the responsibility of AutoManager runtime state.
    """
    materialized = tuple(points)
    if not materialized:
        raise ValueError("AutoManage signal clock requires canonical 1m history")

    if automanage_signal_clock_v2(strategy_key) == SIGNAL_CLOCK_INTRABAR_30M_1M:
        samples = intrabar_macd_samples_v2(materialized, market=market)
        if len(samples) < 2:
            raise ValueError("AutoManage intrabar signal clock needs two 1m-sampled MACD observations")
        previous_sample, current_sample = samples[-2], samples[-1]
        return (
            MacdObservationV2(
                bar_time=previous_sample.action_at,
                macd=previous_sample.macd,
                signal=previous_sample.signal,
            ),
            MacdObservationV2(
                bar_time=current_sample.action_at,
                macd=current_sample.macd,
                signal=current_sample.signal,
            ),
        )

    closed = closed_30m_bars_v2(materialized, market=market)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("AutoManage needs enough closed 30m bars for MACD 12/26/9")
    return observations[-2], observations[-1]


__all__ = [
    "SIGNAL_CLOCK_CLOSED_30M",
    "SIGNAL_CLOCK_INTRABAR_30M_1M",
    "automanage_signal_clock_v2",
    "automanage_signal_pair_v2",
]
