"""Directional MACD histogram turns on completed, contiguous bars."""

from datetime import timedelta
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import MtfObservationV2


def histogram_turn_v1(
    observations: Sequence[MtfObservationV2], *, timeframe_minutes: int
) -> str | None:
    """Two strict consecutive increases -> LONG; two decreases -> SHORT.

    The histogram is MACD minus signal (``spread``). Zero crossings are irrelevant.
    A flat bar, missing interval, or insufficient history never creates a signal.
    """
    if len(observations) < 3:
        return None
    first, previous, current = observations[-3:]
    step = timedelta(minutes=int(timeframe_minutes))
    if previous.closed_at - first.closed_at != step or current.closed_at - previous.closed_at != step:
        return None
    if first.spread < previous.spread < current.spread:
        return "LONG"
    if first.spread > previous.spread > current.spread:
        return "SHORT"
    return None
