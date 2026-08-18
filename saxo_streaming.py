from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import struct
import threading
import time
import uuid
from typing import Any, Callable

from realtime_market_data import (
    MinuteBarAggregator,
    RealtimeBar1m,
    RealtimeMarketDataStore,
    RealtimeQuote,
    StreamStatus,
    minute_start,
    utc,
)
from saxo_provider import LIVE_BASE_URL, SaxoClient, SaxoInstrument, configured_client, configured_instruments


LOGGER = logging.getLogger("pricegauger.saxo_stream")
DEFAULT_REFRESH_MS = 1000
STATUS_HEARTBEAT_SECONDS = 15.0
STREAM_REAUTHORIZE_SECONDS = 15 * 60.0
STREAM_REAUTHORIZE_RETRY_SECONDS = 60.0
BACKFILL_BAR_COUNT = 30
BACKFILL_TIMEOUT_SECONDS = 5.0


class SaxoStreamError(RuntimeError):
    pass


class SaxoStreamReset(SaxoStreamError):
    pass


class SaxoStreamDisconnected(SaxoStreamError):
    pass


@dataclass(frozen=True, slots=True)
class SaxoStreamMessage:
    message_id: int
    reference_id: str
    payload_format: int
    payload: Any


def parse_stream_frame(frame: bytes) -> list[SaxoStreamMessage]:
    """Parse one reassembled WebSocket binary message into Saxo data messages."""
    messages: list[SaxoStreamMessage] = []
    cursor = 0
    total = len(frame)
    while cursor < total:
        if total - cursor < 16:
            raise SaxoStreamError("truncated Saxo stream header")
        message_id = struct.unpack_from("<Q", frame, cursor)[0]
        ref_size = frame[cursor + 10]
        ref_start = cursor + 11
        ref_end = ref_start + ref_size
        if ref_end + 5 > total:
            raise SaxoStreamError("truncated Saxo reference id")
        reference_id = frame[ref_start:ref_end].decode("ascii")
        payload_format = frame[ref_end]
        payload_size = struct.unpack_from("<I", frame, ref_end + 1)[0]
        payload_start = ref_end + 5
        payload_end = payload_start + payload_size
        if payload_end > total:
            raise SaxoStreamError("truncated Saxo payload")
        raw = frame[payload_start:payload_end]
        if payload_format == 0:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SaxoStreamError("invalid JSON stream payload") from exc
        else:
            payload = raw
        messages.append(SaxoStreamMessage(message_id, reference_id, payload_format, payload))
        cursor = payload_end
    return messages


def merge_delta(current: Any, update: Any) -> Any:
    """Apply Saxo's JSON delta compression without discarding unchanged fields."""
    if not isinstance(current, dict) or not isinstance(update, dict):
        return update
    result = dict(current)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_delta(result[key], value)
        else:
            result[key] = value
    return result


def _find_value(payload: Any, names: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for name in names:
            if name in payload and payload[name] is not None:
                return payload[name]
        for value in payload.values():
            found = _find_value(value, names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_value(value, names)
            if found is not None:
                return found
    return None


def quote_from_snapshot(
    *,
    market: str,
    instrument: SaxoInstrument,
    payload: dict[str, Any],
    observed_at: str | None = None,
) -> RealtimeQuote | None:
    bid = _find_value(payload, ("Bid", "BidPrice"))
    ask = _find_value(payload, ("Ask", "AskPrice"))
    last = _find_value(payload, ("LastTraded", "LastTradedPrice", "Price"))
    if bid is None and ask is None and last is None:
        return None
    stamp = observed_at or str(
        _find_value(payload, ("Timestamp", "LastUpdated"))
        or datetime.now(timezone.utc).isoformat()
    )
    multiplier = float(instrument.price_multiplier)
    return RealtimeQuote(
        market=market,
        observed_at=stamp,
        bid=None if bid is None else float(bid) * multiplier,
        ask=None if ask is None else float(ask) * multiplier,
        last=None if last is None else float(last) * multiplier,
        uic=instrument.uic,
        asset_type=instrument.asset_type,
        symbol=instrument.symbol,
    )


def delay_minutes(payload: Any) -> float | None:
    value = _find_value(payload, ("DelayedByMinutes", "DelayMinutes"))
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _stream_base(client: SaxoClient) -> str:
    live = client.base_url.rstrip("/") == LIVE_BASE_URL.rstrip("/")
    if live:
        return "https://live-streaming.saxobank.com/oapi/streaming/ws"
    return "https://sim-streaming.saxobank.com/sim/oapi/streaming/ws"


def _stream_url(client: SaxoClient, context_id: str) -> str:
    """Return Saxo's current plain-WebSocket endpoint for the client's environment."""
    base = _stream_base(client).replace("https://", "wss://", 1)
    return f"{base}/connect?contextId={context_id}"


def _stream_authorize_url(client: SaxoClient, context_id: str) -> str:
    return f"{_stream_base(client)}/authorize?contextid={context_id}"


def _authorize(client: SaxoClient, *, force_refresh: bool = False) -> str:
    # Keep OAuth ownership in the existing Saxo client. The public provider does
    # not yet expose a token accessor, so the streaming adapter uses its auth hook.
    client._set_authorization(force_refresh=force_refresh)  # noqa: SLF001
    value = str(client.session.headers.get("Authorization") or "")
    if not value:
        raise SaxoStreamError("Saxo authorization header unavailable")
    return value


def reauthorize_stream(client: SaxoClient, *, context_id: str) -> None:
    """Refresh OAuth and authorize an already-open Saxo WebSocket context."""
    _authorize(client, force_refresh=True)
    response = client.session.put(
        _stream_authorize_url(client, context_id),
        timeout=client.timeout,
    )
    if response.status_code != 202:
        raise SaxoStreamError(
            f"stream reauthorization rejected HTTP {response.status_code}"
        )


def try_reauthorize_stream(client: SaxoClient, *, context_id: str) -> bool:
    """Attempt reauthorization without sacrificing an otherwise healthy socket.

    Token and REST endpoints can fail transiently even while the WebSocket remains
    healthy. Keep receiving buffered/live stream data and retry shortly instead of
    forcing an immediate reconnect on the first refresh failure.
    """
    try:
        reauthorize_stream(client, context_id=context_id)
    except Exception as exc:
        LOGGER.warning(
            "Saxo stream reauthorization failed; keeping socket open and retrying in %.0fs: %s",
            STREAM_REAUTHORIZE_RETRY_SECONDS,
            exc,
            exc_info=True,
        )
        return False
    return True


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def bars_from_chart_frame(
    frame: Any,
    *,
    market: str,
    instrument: SaxoInstrument,
    now: str | datetime | None = None,
) -> list[RealtimeBar1m]:
    """Convert Saxo chart rows to completed canonical 1m bars.

    The current minute is deliberately excluded. It remains owned by the realtime
    quote aggregator so a partially formed chart candle can never overwrite live
    OHLC data.
    """
    if frame is None or getattr(frame, "empty", True):
        return []
    cutoff = minute_start(now or datetime.now(timezone.utc))
    bars: list[RealtimeBar1m] = []
    for record in frame.to_dict(orient="records"):
        timestamp = record.get("timestamp")
        close = _finite_float(record.get("close"))
        if timestamp is None or close is None:
            continue
        try:
            bar_time = minute_start(utc(timestamp))
        except (TypeError, ValueError):
            continue
        if bar_time >= cutoff:
            continue
        open_price = _finite_float(record.get("open"))
        high_price = _finite_float(record.get("high"))
        low_price = _finite_float(record.get("low"))
        volume = _finite_float(record.get("volume"))
        bars.append(
            RealtimeBar1m(
                market=market,
                bar_time=bar_time.isoformat(),
                open=close if open_price is None else open_price,
                high=close if high_price is None else high_price,
                low=close if low_price is None else low_price,
                close=close,
                sample_count=0,
                provider="Saxo OpenAPI",
                uic=instrument.uic,
                asset_type=instrument.asset_type,
                symbol=instrument.symbol,
                volume=volume,
            )
        )
    return bars


def _backfill_client(client: SaxoClient) -> SaxoClient:
    """Create an isolated short-timeout REST client for asynchronous backfill."""
    static_token = str(getattr(client, "_static_access_token", "") or "").strip()  # noqa: SLF001
    token_getter = getattr(client, "_access_token_getter", None)  # noqa: SLF001
    return SaxoClient(
        access_token=static_token or None,
        access_token_getter=token_getter,
        base_url=client.base_url,
        timeout=min(float(client.timeout), BACKFILL_TIMEOUT_SECONDS),
    )


def create_price_subscription(
    client: SaxoClient,
    *,
    context_id: str,
    reference_id: str,
    instrument: SaxoInstrument,
    refresh_ms: int = DEFAULT_REFRESH_MS,
) -> dict[str, Any]:
    _authorize(client)
    response = client.session.post(
        f"{client.base_url}/trade/v1/prices/subscriptions",
        json={
            "Arguments": {"AssetType": instrument.asset_type, "Uic": int(instrument.uic)},
            "ContextId": context_id,
            "ReferenceId": reference_id,
            "RefreshRate": max(250, int(refresh_ms)),
            "Format": "application/json",
        },
        timeout=client.timeout,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SaxoStreamError(
            f"subscription returned non-JSON HTTP {response.status_code}"
        ) from exc
    if not response.ok:
        raise SaxoStreamError(
            f"subscription rejected HTTP {response.status_code}: {payload}"
        )
    return payload


class SaxoRealtimeService:
    """Long-running Saxo quote stream isolated from the analysis worker."""

    def __init__(
        self,
        *,
        db_path: str = "pricegauger.db",
        client: SaxoClient | None = None,
        instruments: dict[str, SaxoInstrument] | None = None,
        refresh_ms: int = DEFAULT_REFRESH_MS,
    ) -> None:
        self.client = client or configured_client()
        self.instruments = instruments if instruments is not None else configured_instruments()
        self.refresh_ms = max(250, int(refresh_ms))
        self.store = RealtimeMarketDataStore(db_path)
        self.aggregators = {market: MinuteBarAggregator() for market in self.instruments}
        self.reference_to_market: dict[str, str] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self._status_cache: dict[str, StreamStatus] = {
            item.market: item for item in self.store.load_statuses()
        }
        self._last_status_write: dict[str, float] = {}
        self._backfill_lock = threading.Lock()
        self._backfill_thread: threading.Thread | None = None

    def _status(self, market: str, state: str, *, force: bool = True, **kwargs: Any) -> None:
        previous = self._status_cache.get(market)
        status = StreamStatus(
            market=market,
            updated_at=datetime.now(timezone.utc).isoformat(),
            state=state,
            reference_id=str(
                kwargs.get("reference_id")
                if kwargs.get("reference_id") is not None
                else (previous.reference_id if previous else "")
            ),
            requested_refresh_ms=self.refresh_ms,
            actual_refresh_ms=kwargs.get(
                "actual_refresh_ms", previous.actual_refresh_ms if previous else None
            ),
            delay_minutes=kwargs.get(
                "delay_minutes", previous.delay_minutes if previous else None
            ),
            last_quote_at=kwargs.get(
                "last_quote_at", previous.last_quote_at if previous else None
            ),
            detail=str(kwargs.get("detail") or ""),
        )
        self._status_cache[market] = status
        now_mono = time.monotonic()
        last_write = self._last_status_write.get(market, 0.0)
        if force or now_mono - last_write >= STATUS_HEARTBEAT_SECONDS:
            self.store.save_status(status)
            self._last_status_write[market] = now_mono

    def subscribe_all(self, context_id: str) -> None:
        self.reference_to_market.clear()
        self.snapshots.clear()
        for index, (market, instrument) in enumerate(self.instruments.items(), start=1):
            reference_id = f"PG{index:02d}{uuid.uuid4().hex[:8]}"
            try:
                payload = create_price_subscription(
                    self.client,
                    context_id=context_id,
                    reference_id=reference_id,
                    instrument=instrument,
                    refresh_ms=self.refresh_ms,
                )
                snapshot = payload.get("Snapshot") if isinstance(payload, dict) else None
                if not isinstance(snapshot, dict):
                    snapshot = {}
                self.reference_to_market[reference_id.upper()] = market
                self.snapshots[reference_id.upper()] = snapshot
                actual = payload.get("RefreshRate") if isinstance(payload, dict) else None
                delay = delay_minutes(snapshot)
                self._status(
                    market,
                    "SUBSCRIBED",
                    reference_id=reference_id,
                    actual_refresh_ms=None if actual is None else int(actual),
                    delay_minutes=delay,
                    detail="subscription active",
                )
                quote = quote_from_snapshot(
                    market=market, instrument=instrument, payload=snapshot
                )
                if quote is not None:
                    self._consume_quote(quote)
            except Exception as exc:
                self._status(
                    market,
                    "FAILED",
                    detail=f"{type(exc).__name__}: {exc}",
                )
                LOGGER.exception("Saxo subscription failed market=%s", market)

    def _consume_quote(self, quote: RealtimeQuote) -> None:
        completed = self.aggregators[quote.market].add(quote)
        if completed is not None:
            self.store.save_bar(completed)
        self._status(
            quote.market,
            "STREAMING",
            force=False,
            last_quote_at=quote.observed_at,
            detail="quote received",
        )

    def _run_backfill(self) -> None:
        if not self._backfill_lock.acquire(blocking=False):
            return
        try:
            client = _backfill_client(self.client)
            total = 0
            for market, instrument in self.instruments.items():
                try:
                    frame = client.chart(
                        instrument,
                        horizon_minutes=1,
                        count=BACKFILL_BAR_COUNT,
                    )
                    bars = bars_from_chart_frame(
                        frame,
                        market=market,
                        instrument=instrument,
                    )
                    for bar in bars:
                        self.store.save_bar(bar)
                    total += len(bars)
                except Exception as exc:
                    LOGGER.warning(
                        "Saxo 1m backfill failed market=%s: %s",
                        market,
                        exc,
                        exc_info=True,
                    )
            LOGGER.info("Saxo 1m backfill complete bars=%d", total)
        finally:
            self._backfill_lock.release()

    def start_backfill(self) -> bool:
        """Start one non-blocking recent-bar repair job after a successful connect."""
        if self._backfill_thread is not None and self._backfill_thread.is_alive():
            return False
        self._backfill_thread = threading.Thread(
            target=self._run_backfill,
            name="pricegauger-saxo-backfill",
            daemon=True,
        )
        self._backfill_thread.start()
        return True

    def handle_message(
        self,
        message: SaxoStreamMessage,
        *,
        received_at: str | None = None,
    ) -> None:
        ref = message.reference_id.upper()
        if ref.startswith("_"):
            payload = message.payload if isinstance(message.payload, dict) else {}
            if ref == "_RESETSUBSCRIPTIONS":
                raise SaxoStreamReset(
                    str(payload.get("TargetReferenceIds") or "all subscriptions")
                )
            if ref == "_DISCONNECT":
                raise SaxoStreamDisconnected("Saxo requested disconnect")
            return
        market = self.reference_to_market.get(ref)
        if market is None or not isinstance(message.payload, dict):
            return
        current = self.snapshots.get(ref, {})
        merged = merge_delta(current, message.payload)
        self.snapshots[ref] = merged
        instrument = self.instruments[market]
        provider_observed_at = _find_value(
            message.payload,
            ("Timestamp", "LastUpdated"),
        )
        observation_time = str(
            provider_observed_at
            or received_at
            or datetime.now(timezone.utc).isoformat()
        )
        quote = quote_from_snapshot(
            market=market,
            instrument=instrument,
            payload=merged,
            observed_at=observation_time,
        )
        if quote is not None:
            self._consume_quote(quote)

    def run_forever(
        self, *, stop_requested: Callable[[], bool] | None = None
    ) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise SaxoStreamError("websockets dependency is required") from exc
        if self.client is None:
            raise SaxoStreamError("Saxo client is not configured")
        if not self.instruments:
            raise SaxoStreamError("No Saxo instruments are configured")

        stop = stop_requested or (lambda: False)
        backoff = 1.0
        while not stop():
            context_id = f"pgstream-{uuid.uuid4().hex[:16]}"
            try:
                auth = _authorize(self.client, force_refresh=True)
                url = _stream_url(self.client, context_id)
                with connect(
                    url,
                    additional_headers={"Authorization": auth},
                    open_timeout=20,
                    close_timeout=5,
                ) as socket:
                    self.subscribe_all(context_id)
                    self.start_backfill()
                    backoff = 1.0
                    next_reauthorize = time.monotonic() + STREAM_REAUTHORIZE_SECONDS
                    while not stop():
                        if time.monotonic() >= next_reauthorize:
                            if try_reauthorize_stream(self.client, context_id=context_id):
                                next_reauthorize = time.monotonic() + STREAM_REAUTHORIZE_SECONDS
                                LOGGER.info("Saxo stream reauthorized context=%s", context_id)
                            else:
                                next_reauthorize = time.monotonic() + STREAM_REAUTHORIZE_RETRY_SECONDS
                        frame = socket.recv(timeout=45)
                        if isinstance(frame, str):
                            continue
                        for message in parse_stream_frame(bytes(frame)):
                            self.handle_message(message)
            except (SaxoStreamReset, SaxoStreamDisconnected) as exc:
                LOGGER.warning("Saxo stream reset/reconnect: %s", exc)
            except Exception as exc:
                LOGGER.exception(
                    "Saxo realtime stream failed; reconnecting: %s", exc
                )
            if stop():
                break
            time.sleep(backoff)
            backoff = min(30.0, backoff * 2.0)
