"""Bounded missing-history backoff ONLY for offline V2 research shadows.

No LIVE Saxo, V3, risk, stop, watchdog, ingestion or order code imports this.
Each strategy+database+market gets its own short retry deadline. Successful
reads clear the deadline; failures unrelated to missing/warmup history do not.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

RETRY_SECONDS = 120.0


class MissingShadowHistoryRetryV1:
    def __init__(self, *, monotonic: Callable[[], float] | None = None,
                 retry_seconds: float = RETRY_SECONDS) -> None:
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self.retry_seconds = max(1.0, float(retry_seconds))
        self._lock = threading.Lock()
        self._retry_after: dict[tuple[str, str, int], float] = {}

    def should_attempt(self, *, strategy: str, db_path: str, source_id: int) -> bool:
        key = (str(strategy), str(db_path), int(source_id))
        now = self._monotonic()
        with self._lock:
            next_time = self._retry_after.get(key)
            if next_time is None:
                return True
            if now < next_time:
                return False
            self._retry_after.pop(key, None)
            return True

    def record_missing(self, *, strategy: str, db_path: str, source_id: int) -> None:
        key = (str(strategy), str(db_path), int(source_id))
        with self._lock:
            self._retry_after[key] = self._monotonic() + self.retry_seconds

    def mark_available(self, *, strategy: str, db_path: str, source_id: int) -> None:
        key = (str(strategy), str(db_path), int(source_id))
        with self._lock:
            self._retry_after.pop(key, None)


def is_only_missing_shadow_history(exc: Exception, market: str) -> bool:
    """Match only the two known research-only missing data errors, exactly."""
    if type(exc) is not ValueError:
        return False
    return str(exc) in {
        f"no canonical history for {market}",
        f"Cocktail Mode #1 lacks canonical warmup for {market}",
    }


RETRY = MissingShadowHistoryRetryV1()
