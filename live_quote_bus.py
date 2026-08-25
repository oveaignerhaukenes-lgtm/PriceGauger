from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any

from database import database_url, using_postgres
from realtime_market_data import RealtimeBar1m


LOGGER = logging.getLogger("pricegauger.live_quote_bus")
CHANNEL = "pricegauger_live_quote_v1"
_RECONNECT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class LiveBarPulse:
    market: str
    observed_at: str
    bar: RealtimeBar1m

    def to_json(self) -> str:
        return json.dumps(
            {
                "market": self.market,
                "observed_at": self.observed_at,
                "bar": asdict(self.bar),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> "LiveBarPulse":
        raw = json.loads(payload)
        return cls(
            market=str(raw["market"]),
            observed_at=str(raw["observed_at"]),
            bar=RealtimeBar1m(**dict(raw["bar"])),
        )


class LiveQuotePublisher:
    """Transient PostgreSQL NOTIFY publisher; never persists quote payloads."""

    def __init__(self) -> None:
        self._connection: Any | None = None

    def _connection_or_open(self):
        if self._connection is not None and not getattr(self._connection, "closed", False):
            return self._connection
        import psycopg

        self._connection = psycopg.connect(database_url(), autocommit=True, connect_timeout=5)
        return self._connection

    def publish(self, pulse: LiveBarPulse) -> None:
        if not using_postgres():
            return
        payload = pulse.to_json()
        try:
            connection = self._connection_or_open()
            connection.execute("SELECT pg_notify(%s, %s)", (CHANNEL, payload))
        except Exception:
            try:
                if self._connection is not None:
                    self._connection.close()
            except Exception:
                pass
            self._connection = None
            LOGGER.warning("Transient live quote publish failed", exc_info=True)


_LATEST: dict[str, LiveBarPulse] = {}
_LOCK = threading.Lock()
_LISTENER_THREAD: threading.Thread | None = None
_LISTENER_START_LOCK = threading.Lock()


def _store_payload(payload: str) -> None:
    try:
        pulse = LiveBarPulse.from_json(payload)
    except Exception:
        LOGGER.warning("Ignoring malformed live quote notification", exc_info=True)
        return
    with _LOCK:
        _LATEST[pulse.market] = pulse


def _listen_forever() -> None:
    import psycopg

    while True:
        try:
            connection = psycopg.connect(database_url(), autocommit=True, connect_timeout=5)
            connection.execute(f"LISTEN {CHANNEL}")
            for notification in connection.notifies():
                _store_payload(notification.payload)
        except Exception:
            LOGGER.warning("Transient live quote listener disconnected; retrying", exc_info=True)
            time.sleep(_RECONNECT_SECONDS)


def ensure_live_quote_listener() -> None:
    global _LISTENER_THREAD
    if not using_postgres():
        return
    with _LISTENER_START_LOCK:
        if _LISTENER_THREAD is not None and _LISTENER_THREAD.is_alive():
            return
        _LISTENER_THREAD = threading.Thread(
            target=_listen_forever,
            name="pricegauger-live-quote-listener",
            daemon=True,
        )
        _LISTENER_THREAD.start()


def latest_live_pulse(market: str, *, max_age_seconds: float = 10.0) -> LiveBarPulse | None:
    ensure_live_quote_listener()
    with _LOCK:
        pulse = _LATEST.get(market)
    if pulse is None:
        return None
    try:
        observed = datetime.fromisoformat(pulse.observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None
    # Provider timestamps can legitimately be delayed by entitlement. Freshness here
    # is about whether the transport is alive, so accept negative/large market-time age;
    # the stream status separately exposes the provider delay to the user.
    if max_age_seconds > 0 and abs(age) > 24 * 3600:
        return None
    return pulse
