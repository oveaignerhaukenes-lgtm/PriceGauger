from __future__ import annotations

from collections.abc import Callable
import time


def sleep_to_fixed_start_cadence_v2(
    *,
    started_at: float,
    interval_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Sleep only the unused part of a start-to-start cadence interval."""
    interval = max(0.0, float(interval_seconds))
    elapsed = max(0.0, float(monotonic()) - float(started_at))
    remaining = max(0.0, interval - elapsed)
    if remaining > 0.0:
        sleep(remaining)
    return remaining
