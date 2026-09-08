from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autotrader_fast_live_runtime_v2 import DIRECTION_LONG, DIRECTION_SHORT, Macd1mClockV2
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarV2
from database import connect
from saxo_chart_live import FormingCandleStore, forming_candle_event_age_seconds
from trading_desk import ChartBar


# All simple LIVE MACD flip controls share one execution clock. Technical Core still
# consumes only canonical closed history; the forming Saxo candle is execution-only.
LIVE_INTRABAR_MACD_TIMEFRAMES_V1 = (1, 2, 5, 15)
LIVE_INTRABAR_MAX_EVENT_AGE_SECONDS_V1 = 8.0
LIVE_INTRABAR_MAX_PROBE_GAP_SECONDS_V1 = 10 * 60.0


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_macd_intrabar_probe_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_macd_live_probe_state (
                pilot_key TEXT PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                timeframe_minutes INTEGER NOT NULL,
                sampled_at TIMESTAMPTZ NOT NULL,
                source_bar_time TIMESTAMPTZ NOT NULL,
                macd DOUBLE PRECISION NOT NULL,
                signal DOUBLE PRECISION NOT NULL,
                spread DOUBLE PRECISION NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _load_probe_v1(pilot_key: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT strategy_key,timeframe_minutes,sampled_at,source_bar_time,macd,signal,spread
            FROM pg_v2_autotrader_macd_live_probe_state
            WHERE pilot_key=?
            """,
            (str(pilot_key),),
        ).fetchone()
    return None if row is None else dict(row)


def _save_probe_v1(
    *,
    enrollment: StrategyEnrollmentV2,
    timeframe_minutes: int,
    sampled_at: datetime,
    source_bar_time: datetime,
    macd: float,
    signal: float,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_macd_live_probe_state(
                pilot_key,strategy_key,timeframe_minutes,sampled_at,source_bar_time,
                macd,signal,spread,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,now())
            ON CONFLICT(pilot_key) DO UPDATE SET
                strategy_key=excluded.strategy_key,
                timeframe_minutes=excluded.timeframe_minutes,
                sampled_at=excluded.sampled_at,
                source_bar_time=excluded.source_bar_time,
                macd=excluded.macd,
                signal=excluded.signal,
                spread=excluded.spread,
                updated_at=now()
            """,
            (
                str(enrollment.pilot_key),
                str(enrollment.strategy_key),
                int(timeframe_minutes),
                sampled_at,
                source_bar_time,
                float(macd),
                float(signal),
                float(macd - signal),
            ),
        )


def _bucket_start_v1(value: datetime, *, timeframe_minutes: int) -> datetime:
    stamp = _utc(value).replace(second=0, microsecond=0)
    minutes = int(timeframe_minutes)
    epoch_minutes = int(stamp.timestamp() // 60)
    bucket_epoch_minutes = epoch_minutes - (epoch_minutes % minutes)
    return datetime.fromtimestamp(bucket_epoch_minutes * 60, tz=timezone.utc)


def _forming_timeframe_bar_v1(
    *,
    enrollment: StrategyEnrollmentV2,
    bars: tuple[CanonicalMarketBarV2, ...],
    candle,
    timeframe_minutes: int,
) -> ChartBar:
    """Aggregate the entire currently forming timeframe bucket consistently.

    Earlier implementation used only the latest forming 1m candle as the 2m/5m bar.
    That made the live MACD input differ from the eventual closed timeframe candle.
    Here closed canonical 1m samples already inside the current bucket are combined
    with Saxo's current forming 1m candle, so the sampled bar converges to the exact
    same OHLC that the canonical resampler will see at close.
    """
    minutes = int(timeframe_minutes)
    source_bar_time = _utc(candle.bar_time).replace(second=0, microsecond=0)
    bucket_start = _bucket_start_v1(source_bar_time, timeframe_minutes=minutes)
    partial = tuple(
        item
        for item in bars
        if bucket_start <= _utc(item.bar_time).replace(second=0, microsecond=0) < source_bar_time
    )

    opens = [float(item.open) for item in partial] + [float(candle.open)]
    highs = [float(item.high) for item in partial] + [float(candle.high)]
    lows = [float(item.low) for item in partial] + [float(candle.low)]
    volumes = [float(item.volume) for item in partial if item.volume is not None]
    if candle.volume is not None:
        volumes.append(float(candle.volume))

    return ChartBar(
        market=enrollment.market_name,
        bar_time=bucket_start.isoformat(),
        open=opens[0],
        high=max(highs),
        low=min(lows),
        close=float(candle.close),
        volume=(sum(volumes) if volumes else None),
    )


def live_macd_intrabar_clock_v1(
    enrollment: StrategyEnrollmentV2,
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
    db_path: str,
    now: datetime,
) -> Macd1mClockV2:
    """Build a restart-safe LIVE MACD clock from exact history + forming Saxo data.

    The forming candle remains outside canonical Technical Core history. Consecutive
    live MACD samples are persisted by pilot, so browser refreshes cannot reset the
    cross detector and short process restarts retain the previous side of the cross.
    """
    minutes = int(timeframe_minutes)
    if minutes not in LIVE_INTRABAR_MACD_TIMEFRAMES_V1:
        raise ValueError(f"{minutes}m is not enabled for intrabar MACD")
    if not bars:
        raise ValueError(f"MACD {minutes}m LIVE has no canonical warmup")

    store = FormingCandleStore(db_path)
    candle = store.load(market=enrollment.market_name)
    status = store.load_status(market=enrollment.market_name)
    age = forming_candle_event_age_seconds(candle, now=now)
    if candle is None or status is None:
        raise ValueError(f"MACD {minutes}m LIVE lacks forming Saxo candle")
    if str(status.state).upper() != "STREAMING":
        raise ValueError(f"MACD {minutes}m LIVE chart stream is not STREAMING")
    if status.delayed_by_minutes is None or float(status.delayed_by_minutes) > 0.0:
        raise ValueError(f"MACD {minutes}m LIVE forming candle is delayed")
    if age is None or age > LIVE_INTRABAR_MAX_EVENT_AGE_SECONDS_V1:
        raise ValueError(f"MACD {minutes}m LIVE forming candle is stale")
    if int(candle.uic) != int(enrollment.uic) or str(candle.asset_type) != str(enrollment.asset_type):
        raise ValueError(f"MACD {minutes}m LIVE forming candle product mismatch")

    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=enrollment.market_name,
        timeframe_minutes=minutes,
    )
    if not closed:
        raise ValueError(f"MACD {minutes}m LIVE lacks closed MACD warmup")

    source_bar_time = _utc(candle.bar_time).replace(second=0, microsecond=0)
    bucket_start = _bucket_start_v1(source_bar_time, timeframe_minutes=minutes)
    current_bar = _forming_timeframe_bar_v1(
        enrollment=enrollment,
        bars=bars,
        candle=candle,
        timeframe_minutes=minutes,
    )
    materialized = tuple(item for item in closed if _utc(item.bar_time) < bucket_start) + (current_bar,)
    observations = macd_observations_v2(materialized, timeframe_minutes=minutes)
    if not observations:
        raise ValueError(f"MACD {minutes}m LIVE needs enough history for MACD 12/26/9")
    current = observations[-1]
    sampled_at = _utc(candle.updated_at)

    prior = _load_probe_v1(str(enrollment.pilot_key))
    previous_macd = float(current.macd)
    previous_signal = float(current.signal)
    previous_spread = float(current.spread)
    cross = None
    data_gap = True
    if prior is not None:
        prior_sampled_at = _utc(prior["sampled_at"])
        prior_source_bar_time = _utc(prior["source_bar_time"])
        gap_seconds = (sampled_at - prior_sampled_at).total_seconds()
        compatible = (
            str(prior["strategy_key"]) == str(enrollment.strategy_key)
            and int(prior["timeframe_minutes"]) == minutes
            and 0.0 <= gap_seconds <= LIVE_INTRABAR_MAX_PROBE_GAP_SECONDS_V1
            and source_bar_time >= prior_source_bar_time
        )
        if compatible:
            data_gap = False
            previous_macd = float(prior["macd"])
            previous_signal = float(prior["signal"])
            previous_spread = float(prior["spread"])
            if previous_spread <= 0.0 < current.spread:
                cross = DIRECTION_LONG
            elif previous_spread >= 0.0 > current.spread:
                cross = DIRECTION_SHORT

    _save_probe_v1(
        enrollment=enrollment,
        timeframe_minutes=minutes,
        sampled_at=sampled_at,
        source_bar_time=source_bar_time,
        macd=float(current.macd),
        signal=float(current.signal),
    )
    return Macd1mClockV2(
        action_at=sampled_at,
        previous_macd=previous_macd,
        previous_signal=previous_signal,
        previous_spread=previous_spread,
        current_macd=float(current.macd),
        current_signal=float(current.signal),
        current_spread=float(current.spread),
        cross_direction=cross,
        data_gap=data_gap,
    )


__all__ = [
    "LIVE_INTRABAR_MACD_TIMEFRAMES_V1",
    "ensure_macd_intrabar_probe_schema_v1",
    "live_macd_intrabar_clock_v1",
]
