from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from database import connect
from saxo_provider import SaxoClient, SaxoInstrument
from trading_desk import ChartBar, timeframe_minutes, utc


CHART_STREAM_REFRESH_MS = 1000
LIVE_CHART_ACTIVE_REFRESH_SECONDS = 1
LIVE_CHART_IDLE_REFRESH_SECONDS = 5
LIVE_CHART_ACTIVE_EVENT_MAX_AGE_SECONDS = 8


@dataclass(frozen=True, slots=True)
class FormingCandle1m:
    """Presentation-only 1m candle from Saxo chart streaming.

    This object is deliberately kept outside canonical market bars. It represents
    the provider's currently forming chart sample and may therefore change until
    Saxo advances to the next sample. Technical Core must never consume it.
    """

    market: str
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    provider: str
    uic: int
    asset_type: str
    symbol: str
    delayed_by_minutes: float | None
    source_event_at: str
    updated_at: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChartStreamStatus:
    market: str
    state: str
    reference_id: str
    requested_refresh_ms: int
    actual_refresh_ms: int | None
    delayed_by_minutes: float | None
    last_event_at: str | None
    last_candle_at: str | None
    error: str | None
    updated_at: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class FormingCandleStore:
    """Small presentation read-model; never writes pg_v2_market_bars_1m."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS realtime_forming_candles_1m (
                    market TEXT PRIMARY KEY,
                    bar_time TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_realtime_forming_candle_time
                    ON realtime_forming_candles_1m(bar_time);

                CREATE TABLE IF NOT EXISTS realtime_chart_stream_status (
                    market TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def save(self, candle: FormingCandle1m) -> None:
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO realtime_forming_candles_1m(market,bar_time,updated_at,payload_json)
                   VALUES (?,?,?,?)
                   ON CONFLICT(market) DO UPDATE SET
                     bar_time=excluded.bar_time,
                     updated_at=excluded.updated_at,
                     payload_json=excluded.payload_json""",
                (
                    candle.market,
                    candle.bar_time,
                    candle.updated_at,
                    json.dumps(candle.to_record(), sort_keys=True),
                ),
            )

    def load(self, *, market: str) -> FormingCandle1m | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT payload_json FROM realtime_forming_candles_1m WHERE market=?",
                (market,),
            ).fetchone()
        return None if row is None else FormingCandle1m(**json.loads(row["payload_json"]))

    def save_status(self, status: ChartStreamStatus) -> None:
        with connect(self.path) as db:
            db.execute(
                """INSERT INTO realtime_chart_stream_status(market,state,updated_at,payload_json)
                   VALUES (?,?,?,?)
                   ON CONFLICT(market) DO UPDATE SET
                     state=excluded.state,
                     updated_at=excluded.updated_at,
                     payload_json=excluded.payload_json""",
                (
                    status.market,
                    status.state,
                    status.updated_at,
                    json.dumps(status.to_record(), sort_keys=True),
                ),
            )

    def load_status(self, *, market: str) -> ChartStreamStatus | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT payload_json FROM realtime_chart_stream_status WHERE market=?",
                (market,),
            ).fetchone()
        return None if row is None else ChartStreamStatus(**json.loads(row["payload_json"]))

    def load_statuses(self) -> tuple[ChartStreamStatus, ...]:
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT payload_json FROM realtime_chart_stream_status ORDER BY market"
            ).fetchall()
        return tuple(ChartStreamStatus(**json.loads(row["payload_json"])) for row in rows)


def forming_candle_event_age_seconds(
    candle: FormingCandle1m | None,
    *,
    now: datetime | None = None,
) -> float | None:
    if candle is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - utc(candle.updated_at)).total_seconds())


def live_chart_refresh_seconds(
    candle: FormingCandle1m | None,
    *,
    now: datetime | None = None,
) -> int:
    age = forming_candle_event_age_seconds(candle, now=now)
    if age is not None and age <= LIVE_CHART_ACTIVE_EVENT_MAX_AGE_SECONDS:
        return LIVE_CHART_ACTIVE_REFRESH_SECONDS
    return LIVE_CHART_IDLE_REFRESH_SECONDS


def create_chart_subscription(
    client: SaxoClient,
    *,
    context_id: str,
    reference_id: str,
    instrument: SaxoInstrument,
    refresh_ms: int = CHART_STREAM_REFRESH_MS,
) -> dict[str, Any]:
    """Subscribe to Saxo's 1m chart updates on the existing streaming context."""

    client._set_authorization()  # noqa: SLF001 - same authenticated client contract as price streaming
    response = client.session.post(
        f"{client.base_url}/chart/v3/charts/subscriptions",
        json={
            "Arguments": {
                "AssetType": instrument.asset_type,
                "Uic": int(instrument.uic),
                "Horizon": 1,
                "Count": 2,
                "FieldGroups": ["Data", "ChartInfo"],
            },
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
        raise RuntimeError(
            f"chart subscription returned non-JSON HTTP {response.status_code}"
        ) from exc
    if not response.ok:
        raise RuntimeError(
            f"chart subscription rejected HTTP {response.status_code}: {payload}"
        )
    return payload if isinstance(payload, dict) else {}


def chart_delay_minutes(payload: Mapping[str, Any] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    chart_info = payload.get("ChartInfo")
    if not isinstance(chart_info, Mapping):
        data = payload.get("Data")
        if isinstance(data, Mapping):
            chart_info = data.get("ChartInfo")
    if not isinstance(chart_info, Mapping):
        return None
    value = chart_info.get("DelayedByMinutes")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _chart_response(payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    nested = payload.get("Data")
    if isinstance(nested, Mapping) and isinstance(nested.get("Data"), list):
        return nested
    return payload


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_price(row: Mapping[str, Any], stem: str) -> float | None:
    for key in (f"{stem}Bid", stem, f"{stem}Ask"):
        value = _finite(row.get(key))
        if value is not None:
            return value
    return None


def forming_candle_from_chart_payload(
    *,
    market: str,
    instrument: SaxoInstrument,
    payload: Any,
    source_event_at: str | None = None,
    delayed_by_minutes: float | None = None,
) -> FormingCandle1m | None:
    response = _chart_response(payload)
    if response is None:
        return None
    rows = response.get("Data")
    if not isinstance(rows, list) or not rows:
        return None

    usable: list[tuple[datetime, Mapping[str, Any]]] = []
    for item in rows:
        if not isinstance(item, Mapping) or item.get("Time") is None:
            continue
        try:
            stamp = utc(str(item["Time"]))
        except (TypeError, ValueError):
            continue
        usable.append((stamp, item))
    if not usable:
        return None

    stamp, row = max(usable, key=lambda item: item[0])
    open_price = _row_price(row, "Open")
    high_price = _row_price(row, "High")
    low_price = _row_price(row, "Low")
    close_price = _row_price(row, "Close")
    if None in {open_price, high_price, low_price, close_price}:
        return None

    multiplier = float(instrument.price_multiplier)
    open_value = float(open_price) * multiplier
    high_value = float(high_price) * multiplier
    low_value = float(low_price) * multiplier
    close_value = float(close_price) * multiplier
    if high_value < max(open_value, low_value, close_value):
        return None
    if low_value > min(open_value, high_value, close_value):
        return None

    volume = _finite(row.get("Volume"))
    event_at = source_event_at or datetime.now(timezone.utc).isoformat()
    delay = chart_delay_minutes(response)
    if delay is None:
        delay = delayed_by_minutes
    return FormingCandle1m(
        market=market,
        bar_time=stamp.replace(second=0, microsecond=0).isoformat(),
        open=open_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=volume,
        provider="Saxo chart stream",
        uic=int(instrument.uic),
        asset_type=instrument.asset_type,
        symbol=instrument.symbol,
        delayed_by_minutes=delay,
        source_event_at=str(event_at),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def merge_forming_candle_for_display(
    completed: Sequence[ChartBar],
    *,
    forming: FormingCandle1m | None,
    timeframe: str | int,
) -> tuple[ChartBar, ...]:
    """Overlay the forming sample onto chart bars without mutating analysis data."""

    result = list(completed)
    if forming is None:
        return tuple(result)

    minutes = timeframe_minutes(timeframe)
    stamp = utc(forming.bar_time)
    bucket_seconds = minutes * 60
    epoch = int(stamp.timestamp())
    bucket = datetime.fromtimestamp(epoch - (epoch % bucket_seconds), tz=timezone.utc)

    if result:
        last_bucket = utc(result[-1].bar_time)
        if bucket < last_bucket:
            return tuple(result)
        if bucket == last_bucket:
            current = result[-1]
            result[-1] = ChartBar(
                market=current.market,
                bar_time=current.bar_time,
                open=current.open,
                high=max(current.high, forming.high),
                low=min(current.low, forming.low),
                close=forming.close,
                volume=forming.volume if minutes == 1 else None,
            )
            return tuple(result)

    result.append(
        ChartBar(
            market=forming.market,
            bar_time=bucket.isoformat(),
            open=forming.open,
            high=forming.high,
            low=forming.low,
            close=forming.close,
            volume=forming.volume if minutes == 1 else None,
        )
    )
    return tuple(result)
