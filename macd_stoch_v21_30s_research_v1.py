"""Research-only 15s vs 30s vs 1m MACD+Stoch V2.1 on genuine archived Saxo BBO.

Never routes to broker, config, LIVE strategy registry or execution. Both
cadences use completed bars reconstructed from received, timestamped bid/ask.
Marks and hypothetical fills use observable BBO *after* candle close, never
the same candle's closing price. Point-lot P/L has no NOK conversion, funding,
broker margin, commissions, market impact or actual fills.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from trading_desk import ChartBar

MAX_QUOTES = 65000
MIN_SEGMENT_BARS = 55
MAX_QUOTE_AGE_SECONDS = 5


@dataclass(frozen=True)
class Quote30V1:
    at: datetime
    received_at: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class CompletedBar30V1:
    bar: ChartBar
    samples: int
    closed_at: datetime


@dataclass(frozen=True)
class PaperFill30V1:
    at: str
    closed_bar: str
    action: str
    before: float
    after: float
    price: float
    bid: float
    ask: float
    equity_points_lots: float


@dataclass(frozen=True)
class PaperResult30V1:
    interval_seconds: int
    total_quotes: int
    bars: int
    segments: int
    modeled_bars: int
    actions: tuple[PaperFill30V1, ...]
    hypothetical_pnl_points_lots: float | None
    max_drawdown_points_lots: float | None
    last_mark_at: str | None
    skipped_no_fill: int
    first_bar: str | None
    last_bar: str | None


def _utc(x) -> datetime:
    t = x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("quote timestamp must include timezone")
    return t.astimezone(timezone.utc)


def validate_quotes_v1(rows: Sequence) -> tuple[Quote30V1, ...]:
    if len(rows) > MAX_QUOTES:
        raise ValueError("quote research request exceeds fixed bound")
    result = []
    before = None
    for row in rows:
        at = _utc(row["quote_at"] if isinstance(row, dict) else row.quote_at)
        received = _utc(row["received_at"] if isinstance(row, dict) else row.received_at)
        bid = float(row["bid"] if isinstance(row, dict) else row.bid)
        ask = float(row["ask"] if isinstance(row, dict) else row.ask)
        if (not isfinite(bid) or not isfinite(ask) or bid <= 0 or ask < bid
                or (before is not None and at <= before)):
            raise ValueError("invalid, duplicate, or unordered exact-UID BBO quotes")
        lag = (received - at).total_seconds()
        if lag < -2 or lag > 5:
            raise ValueError("delayed or future Saxo quote (strict capture quality)")
        result.append(Quote30V1(at, received, bid, ask))
        before = at
    return tuple(result)


def build_completed_bars_v1(
    quotes: Sequence[Quote30V1], *, interval_seconds: int, market: str,
    observed_through: datetime,
) -> tuple[CompletedBar30V1, ...]:
    if interval_seconds not in (15, 30, 60):
        raise ValueError("only native 15s, 30s, and 1m are supported")
    cutoff = _utc(observed_through)
    windows: list[list[Quote30V1]] = []
    starts: list[datetime] = []
    last = None
    for q in quotes:
        bucket = datetime.fromtimestamp(
            int(q.at.timestamp()) // interval_seconds * interval_seconds,
            tz=timezone.utc,
        )
        if bucket != last:
            starts.append(bucket)
            windows.append([])
            last = bucket
        windows[-1].append(q)
    minimum = max(5, interval_seconds // 4)
    completed = []
    for start, rows in zip(starts, windows):
        end = start + timedelta(seconds=interval_seconds)
        if end > cutoff or len(rows) < minimum:
            continue
        # Do not form candles from a single old quote or bridge stale holes.
        if (rows[0].at - start).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            continue
        if (end - rows[-1].at).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            continue
        if any((b.at - a.at).total_seconds() > MAX_QUOTE_AGE_SECONDS
               for a, b in zip(rows, rows[1:])):
            continue
        prices = [q.mid for q in rows]
        completed.append(CompletedBar30V1(
            ChartBar(market=market, bar_time=start.isoformat(),
                     open=prices[0], high=max(prices), low=min(prices),
                     close=prices[-1], volume=None),
            len(rows), end
        ))
    return tuple(completed)


def _contiguous(bars: Sequence[CompletedBar30V1], seconds: int):
    result = []
    for bar in bars:
        if not result or (bar.closed_at - result[-1][-1].closed_at).total_seconds() != seconds:
            result.append([])
        result[-1].append(bar)
    return result


def _mark(cash: float, pos: float, quote: Quote30V1) -> float:
    # Liquidation-based marking reflects bid for longs and ask for shorts.
    return cash + pos * (quote.bid if pos > 0 else quote.ask if pos < 0 else quote.mid)


def run_v21_quote_paper_v1(
    quotes: Sequence[Quote30V1], *, seconds: int,
    market: str = "US Tech 100 NAS", observed_through: datetime,
    tranche: float = .01, max_inventory: float = .03,
) -> PaperResult30V1:
    """Deterministic replay. Missing bar/quote => no invented trade."""
    bars = build_completed_bars_v1(
        quotes, interval_seconds=seconds, market=market,
        observed_through=observed_through,
    )
    segments = _contiguous(bars, seconds)
    stamp = [q.at for q in quotes]
    settings = MacdTrailingConfigV3(tranche=tranche, max_inventory=max_inventory)
    cash = 0.
    all_actions = []
    marks: list[float] = []
    skipped = modeled = 0
    last_at = None
    assessed = 0
    for segment in segments:
        # Restart in FLAT for each distinct session. Results remain PAPER:
        # only segments whose inventory is fully closed can be scored.
        if len(segment) < MIN_SEGMENT_BARS:
            continue
        full_bars = tuple(x.bar for x in segment)
        observations = macd_observations_v2(full_bars, timeframe_minutes=1)
        by_time = {x.bar_time.isoformat(): x for x in observations}
        position = 0.
        local_cash = 0.
        local_actions: list[PaperFill30V1] = []
        local_marks: list[float] = []
        local_skipped = 0
        local_modeled = 0
        local_last = None
        for i in range(1, len(segment)):
            item = segment[i]
            ob = by_time.get(item.bar.bar_time)
            prior = by_time.get(segment[i-1].bar.bar_time)
            if ob is None or prior is None:
                continue
            end = item.closed_at
            k = bisect_left(stamp, end)
            if k >= len(quotes):
                local_skipped += 1
                continue
            quote = quotes[k]
            # A genuine new BBO must arrive promptly after candle closed,
            # otherwise skip and never backfill a fake market order.
            if (quote.at - end).total_seconds() > MAX_QUOTE_AGE_SECONDS:
                local_skipped += 1
                continue
            decision = macd_stoch_v21_target_v3(
                current_target=TargetInventoryV3(position),
                observation=ob, previous_observation=prior,
                bars=full_bars[:i+1], config=settings,
            )
            local_modeled += 1
            new_pos = float(decision.target.amount)
            delta = round(new_pos - position, 10)
            if abs(delta) > 1.e-9:
                fill = quote.ask if delta > 0 else quote.bid
                local_cash -= delta * fill
                before = position
                position = new_pos
                local_actions.append(PaperFill30V1(
                    quote.at.isoformat(), item.bar.bar_time, decision.action,
                    before, position, fill, quote.bid, quote.ask,
                    _mark(local_cash, position, quote),
                ))
            local_marks.append(_mark(local_cash, position, quote))
            local_last = quote.at.isoformat()
        if local_modeled == 0:
            continue
        # No forced liquidation at gaps or test boundary with knowledge
        # unavailable at the time. Score only fully closed runs. Incomplete
        # runs are excluded, rather than generating fictional exit fills.
        if abs(position) > 1.e-9:
            skipped += local_skipped + 1
            continue
        assessed += 1
        skipped += local_skipped
        modeled += local_modeled
        all_actions.extend(local_actions)
        marks.extend([cash + x for x in local_marks])
        cash += local_cash
        last_at = local_last
    if assessed == 0 or not marks:
        pnl = dd = None
    else:
        pnl = cash
        peak = 0.
        dd = 0.
        for mark in marks:
            peak = max(peak, mark)
            dd = max(dd, peak - mark)
    return PaperResult30V1(
        seconds, len(quotes), len(bars), len(segments), modeled,
        tuple(all_actions), pnl, dd, last_at, skipped,
        bars[0].bar.bar_time if bars else None,
        bars[-1].bar.bar_time if bars else None,
    )
