"""Process-wide, bounded Saxo LIVE HTTP counters; no extra API requests.

Measure actual REST requests (including failures), not streaming quote updates.
Paths are normalized: never log account keys, credentials or order IDs.
"""
from __future__ import annotations

from collections import Counter
import logging
import math
import threading
import time

LOGGER = logging.getLogger("pricegauger.saxo.rest")
_LOCK = threading.Lock()
_STARTED = time.monotonic()
_COUNTS: Counter[tuple[str, str]] = Counter()
_RATE_LIMITED: Counter[tuple[str, str]] = Counter()
_RATE_REMAINING: dict[tuple[str, str], str] = {}
_LATENCY_SECONDS: dict[tuple[str, str], list[float]] = {}
_MAX_LATENCY_SAMPLES_PER_ENDPOINT = 300
REPORT_SECONDS = 60.0


def normalized_saxo_endpoint_v1(path: str) -> str:
    parts = str(path).split("?")[0].strip("/").lower().split("/")
    if len(parts) >= 4 and parts[:4] == ["trade", "v2", "orders", "precheck"]:
        return "trade/v2/orders/precheck"
    if len(parts) >= 4 and parts[:3] == ["ref", "v1", "instruments"]:
        return "ref/v1/instruments/details"
    if len(parts) >= 3:
        return "/".join(parts[:3])
    return "/".join(parts)


def record_saxo_http_v1(
    method: str, path: str, status_code: int, *, headers=None,
    now: float | None = None, latency_seconds: float | None = None,
) -> None:
    """Report aggregate per-endpoint HTTP usage at most once per minute."""
    global _STARTED
    when = time.monotonic() if now is None else float(now)
    key = (str(method).upper(), normalized_saxo_endpoint_v1(path))
    remaining = None
    if headers:
        try:
            remaining = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
        except AttributeError:
            pass
    with _LOCK:
        _COUNTS[key] += 1
        if latency_seconds is not None:
            try:
                duration = float(latency_seconds)
                if math.isfinite(duration) and 0 <= duration <= 300:
                    values = _LATENCY_SECONDS.setdefault(key, [])
                    if len(values) < _MAX_LATENCY_SAMPLES_PER_ENDPOINT:
                        values.append(duration)
            except (TypeError, ValueError):
                pass
        if int(status_code) == 429:
            _RATE_LIMITED[key] += 1
        if remaining is not None:
            _RATE_REMAINING[key] = str(remaining)[:30]
        if when - _STARTED < REPORT_SECONDS:
            return
        parts = []
        for (verb, endpoint), count in sorted(_COUNTS.items()):
            misses = _RATE_LIMITED[(verb, endpoint)]
            headroom = _RATE_REMAINING.get((verb, endpoint))
            durations = sorted(_LATENCY_SECONDS.get((verb, endpoint), []))
            tails = ""
            if durations:
                def percentile(p: float) -> int:
                    return round(durations[min(len(durations)-1,int(len(durations)*p))]*1000)
                tails = (
                    f",n={len(durations)},p50_ms={percentile(.50)},"
                    f"p95_ms={percentile(.95)},p99_ms={percentile(.99)}"
                )
            parts.append(
                f"{verb}:{endpoint}={count}/min(429={misses}"
                + (f",remaining={headroom}" if headroom is not None else "")
                + tails + ")"
            )
        LOGGER.info("Saxo LIVE REST usage 60s %s", " ".join(parts))
        _COUNTS.clear()
        _RATE_LIMITED.clear()
        _RATE_REMAINING.clear()
        _LATENCY_SECONDS.clear()
        _STARTED = when
