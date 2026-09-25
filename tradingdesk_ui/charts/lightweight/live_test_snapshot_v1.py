"""The same closed + forming candle snapshot for Live Chart and TradingDesk."""

from datetime import datetime, timedelta, timezone

from realtime_market_data import RealtimeMarketDataStore
from saxo_chart_live import FormingCandle1m, FormingCandleStore, forming_candle_event_age_seconds
from trading_desk import TIMEFRAME_MINUTES, resample_bars, utc


def load_live_test_snapshot_v1(*, market, timeframe, window_hours, instrument):
    store = RealtimeMarketDataStore()
    raw = store.load_range(
        market=market, start=datetime.now(timezone.utc) - timedelta(hours=int(window_hours)),
        end=datetime.now(timezone.utc), limit=20000,
    )
    closed = resample_bars(raw, timeframe=timeframe)
    try:
        candidate = FormingCandleStore().load(market=market)
    except Exception:
        candidate = None

    forming = None
    if (
        candidate is not None
        and str(candidate.uic) == str(instrument.provider_instrument_id)
        and candidate.asset_type == instrument.asset_type
        and (forming_candle_event_age_seconds(candidate) or 0.0) <= 8.0
    ):
        minutes = TIMEFRAME_MINUTES[timeframe]
        if minutes == 1:
            forming = candidate
        else:
            current_at = utc(candidate.bar_time)
            bucket_seconds = minutes * 60
            bucket_epoch = int(current_at.timestamp()) - (int(current_at.timestamp()) % bucket_seconds)
            bucket_at = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
            bucket_raw = [item for item in raw if bucket_at <= utc(item.bar_time) < current_at]
            open_price = float(bucket_raw[0].open) if bucket_raw else float(candidate.open)
            highs = [float(item.high) for item in bucket_raw] + [float(candidate.high)]
            lows = [float(item.low) for item in bucket_raw] + [float(candidate.low)]
            forming = FormingCandle1m(
                market=candidate.market, bar_time=bucket_at.isoformat(),
                open=open_price, high=max(highs), low=min(lows), close=float(candidate.close),
                volume=candidate.volume, provider=candidate.provider, uic=int(candidate.uic),
                asset_type=candidate.asset_type, symbol=candidate.symbol,
                delayed_by_minutes=candidate.delayed_by_minutes,
                source_event_at=candidate.source_event_at, updated_at=candidate.updated_at,
            )
    return closed, forming
