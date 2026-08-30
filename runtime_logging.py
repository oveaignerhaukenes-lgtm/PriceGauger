from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time


_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_TARGET_RAILWAY_SERVICES = {"PriceGauger-stream", "PriceGauger-worker"}
_RISK_LOGGER = "pricegauger.autotrader.risk_control_v2"
_OBSERVER_REPEAT_SECONDS = 300.0
_POSITION_RE = re.compile(r"\bposition=([^ ]+)")
_REASON_RE = re.compile(r"\breason=([^ ]+)")


class _BelowWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


class ObserverRiskRepeatThrottle(logging.Filter):
    """Keep one observer-only risk warning, then suppress identical repeats briefly.

    RiskControl persistence/execution semantics are untouched. This filter only keeps
    an already-latched, non-executable portfolio observation from filling Railway's
    warning stream every evaluation cycle.
    """

    def __init__(self, *, repeat_seconds: float = _OBSERVER_REPEAT_SECONDS) -> None:
        super().__init__()
        self.repeat_seconds = max(0.0, float(repeat_seconds))
        self._last_seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(record: logging.LogRecord) -> tuple[str, str] | None:
        if record.name != _RISK_LOGGER:
            return None
        message = record.getMessage()
        if not message.startswith("risk control position=") or "eligible=False" not in message:
            return None
        position = _POSITION_RE.search(message)
        reason = _REASON_RE.search(message)
        return (
            "?" if position is None else position.group(1),
            "?" if reason is None else reason.group(1),
        )

    def filter(self, record: logging.LogRecord) -> bool:
        key = self._key(record)
        if key is None:
            return True
        now = time.monotonic()
        with self._lock:
            previous = self._last_seen.get(key)
            if previous is not None and now - previous < self.repeat_seconds:
                return False
            self._last_seen[key] = now
        return True


def configure_runtime_logging(*, level: str | int | None = None) -> None:
    """Configure process logging so Railway severity reflects Python severity."""
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        resolved_level = getattr(logging, level.strip().upper(), logging.INFO)
    else:
        resolved_level = int(level)

    formatter = logging.Formatter(_FORMAT)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_BelowWarning())
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.addFilter(ObserverRiskRepeatThrottle())
    stderr_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(resolved_level)
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)


def configure_railway_runtime_logging_if_applicable() -> bool:
    """Apply split logging only to PriceGauger's long-running Railway workers."""
    service_name = os.getenv("RAILWAY_SERVICE_NAME", "").strip()
    if service_name not in _TARGET_RAILWAY_SERVICES:
        return False
    configure_runtime_logging()
    return True


__all__ = [
    "ObserverRiskRepeatThrottle",
    "configure_railway_runtime_logging_if_applicable",
    "configure_runtime_logging",
]
