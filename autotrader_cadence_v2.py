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
    remaining = interval - elapsed
    if remaining <= 0.0 and interval > 0.0:
        # A slow/failed network call must not turn an overrun into a hot retry loop.
        remaining = min(interval, 1.0)
    remaining = max(0.0, remaining)
    if remaining > 0.0:
        sleep(remaining)
    return remaining
