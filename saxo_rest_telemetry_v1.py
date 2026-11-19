"""Process-wide, bounded Saxo LIVE HTTP counters; no extra API requests.

Measure actual REST requests (including failures), not streaming quote updates.
Paths are normalized: never log account keys, credentials or order IDs.
"""
from __future__ import annotations

from collections import Counter
from collections import deque
from datetime import datetime, timezone
import logging
import math
import re
import threading
import time

LOGGER = logging.getLogger("pricegauger.saxo.rest")
_LOCK = threading.Lock()
_STARTED = time.monotonic()
_COUNTS: Counter[tuple[str, str]] = Counter()
_RATE_LIMITED: Counter[tuple[str, str]] = Counter()
_RATE_REMAINING: dict[tuple[str, str], str] = {}
_LATENCY_SECONDS: dict[tuple[str, str], list[float]] = {}
_QUOTA_HEADERS: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
_OUTBOX: deque[dict] = deque(maxlen=1000)
_RATE_HEADER = re.compile(r"^x-ratelimit-([a-z0-9]+)-(limit|remaining|reset)$",re.I)
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
    quota_headers: dict[str, dict[str, int]] = {}
    if headers:
        try:
            remaining = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
        except AttributeError:
            pass
        try:
            for label,value in headers.items():
                matched=_RATE_HEADER.fullmatch(str(label))
                if not matched:
                    continue
                number=int(str(value).strip())
                if number<0 or number>10**12:
                    continue
                dimension=matched.group(1).lower()
                quota_headers.setdefault(dimension,{})[matched.group(2).lower()]=number
        except (AttributeError,ValueError,TypeError):
            quota_headers={}
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
        if quota_headers:
            # The newest response is a genuine Saxo observation, not an
            # invented allocation of quotas across app processes/sessions.
            _QUOTA_HEADERS[key]=quota_headers
        if when - _STARTED < REPORT_SECONDS:
            return
        window_end=datetime.now(timezone.utc).isoformat()
        parts = []
        for (verb, endpoint), count in sorted(_COUNTS.items()):
            misses = _RATE_LIMITED[(verb, endpoint)]
            _OUTBOX.append({
                'window_ended_at':window_end,
                'method':verb,'endpoint':endpoint,
                'call_count':int(count),'http429_count':int(misses),
                'quota':{dim:dict(metrics) for dim,metrics in
                         _QUOTA_HEADERS.get((verb,endpoint),{}).items()},
            })
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
        _QUOTA_HEADERS.clear()
        _STARTED = when


def drain_saxo_rest_usage_v1() -> tuple[dict, ...]:
    """One cheap queue swap; DB I/O belongs to the independent sidecar."""
    with _LOCK:
        pending=tuple(_OUTBOX)
        _OUTBOX.clear()
    return pending


def restore_saxo_rest_usage_v1(pending) -> None:
    """Retain measurements if the sidecar DB write failed."""
    with _LOCK:
        for row in reversed(tuple(pending)):
            _OUTBOX.appendleft(row)
