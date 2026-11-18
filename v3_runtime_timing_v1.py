"""Read-only per-phase timing for V3 LIVE; no Saxo, DB or order calls."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
import threading
import time

LOGGER = logging.getLogger("pricegauger.v3.timing")
_LOCK = threading.Lock()
_STARTED = time.monotonic()
_SAMPLES: dict[str, list[float]] = {}
_WINDOW_SECONDS = 60.0
# A phase should never be allowed to change trading behavior, even if callers
# accidentally supply an invalid value. No account IDs or price data are logged.
_ALLOWED = frozenset({
    "accounts", "inventory", "instrument_rules", "db_acquire", "decision",
    "modifiers", "cost_guard", "capital_sizing", "precheck", "submit",
    "decision_to_submit", "quote_to_submit"
})


def record_v3_phase_v1(phase: str, elapsed_seconds: float, *, now: float | None = None) -> None:
    global _STARTED
    if phase not in _ALLOWED:
        return
    try:
        elapsed = float(elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            return
    except (ValueError, TypeError):
        return
    current = time.monotonic() if now is None else float(now)
    with _LOCK:
        samples = _SAMPLES.setdefault(phase, [])
        if len(samples) < 300:
            samples.append(elapsed)
        # The bounded sample represents the earliest 300 observations.
        # This is timing diagnostics, never a trading/control input.
        if current - _STARTED < _WINDOW_SECONDS:
            return
        summaries = []
        for name, values in sorted(_SAMPLES.items()):
            if not values:
                continue
            ordered = sorted(values)
            p50 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.50))]
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
            avg = sum(ordered) / len(ordered)
            summaries.append(
                f"{name}:n={len(ordered)},avg_ms={avg*1000:.0f},"
                f"p50_ms={p50*1000:.0f},p95_ms={p95*1000:.0f},"
                f"p99_ms={p99*1000:.0f},max_ms={ordered[-1]*1000:.0f}"
            )
        LOGGER.info("v3 LIVE PHASE 60s %s", " ".join(summaries))
        _SAMPLES.clear()
        _STARTED = current


def record_v3_quote_submit_age_v1(decision_key: str, *, now=None) -> None:
    """Measure source quote age immediately BEFORE broker POST, never a fill lag.

    No database/Saxo calls. A tick impulse may predate the latest quote; this
    metric is explicitly quote-to-submission age, NOT impulse-to-fill latency.
    """
    try:
        key = str(decision_key)
        if not key.startswith(("tick:", "quote10:")):
            return
        stamp = key.split(":", 2)[2].rsplit(":", 1)[0]
        quoted = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if quoted.tzinfo is None:
            return
        current = now or datetime.now(timezone.utc)
        age = (current - quoted.astimezone(timezone.utc)).total_seconds()
        if 0 <= age <= 600:
            record_v3_phase_v1("quote_to_submit", age)
    except (IndexError, TypeError, ValueError, AttributeError):
        return
