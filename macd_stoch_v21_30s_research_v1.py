"""Research-only 15s vs 30s vs 1m MACD+Stoch V2.1 on genuine archived Saxo BBO.

Never routes to broker, config, LIVE strategy registry or execution. All
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

from autotrader_macd_dry_run_v2 import MacdObservationV2
from trading_desk_indicators import calculate_indicators
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_stoch_v2 import ENTRY_THRESHOLD
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from trading_desk import ChartBar

MAX_QUOTES = 65000
MIN_SEGMENT_BARS = 55
MAX_QUOTE_AGE_SECONDS = 5
COMMON_WARMUP_SECONDS = 60 * 60


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
    reversal_mode: str = "flat_first"
    hypothetical_latency_seconds: int = 0
    incomplete_segments: int = 0
    marked_unrealized_points_lots: float = 0.
    completed_pnl_points_lots: float = 0.


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


def _macd_observations_native(bars: tuple[ChartBar, ...]):
    """MACD features built from genuine native-timeframe bars (not 1m labels)."""
    values = calculate_indicators(
        bars, macd_fast=12, macd_slow=26, macd_signal=9,
    )
    macd = {_utc(x.bar_time): float(x.value) for x in values.macd}
    signal = {_utc(x.bar_time): float(x.value) for x in values.macd_signal}
    return tuple(
        MacdObservationV2(bar_time=at, macd=macd[at], signal=signal[at])
        for at in sorted(set(macd).intersection(signal))
    )


def _hypothetical_target(decision, position: float, *, reversal_mode: str,
                         tranche: float) -> tuple[float, str]:
    """Quote-reversal proposal, only for PAPER; NEVER broker-authorized."""
    target = float(decision.target.amount)
    action = decision.action
    if (reversal_mode == "direct_1bar" and action == "OPPOSITE_FLAT"
            and abs(position) >= tranche / 2
            and abs(decision.composite_score) >= ENTRY_THRESHOLD):
        # Strong opposite composite on this CLOSED bar: skip mandatory
        # FLAT-next-bar wait in simulated strategy, use one NET order.
        # In real Saxo LIVE, inventory+margin/order gates still apply.
        side = 1 if decision.composite_score > 0 else -1
        target = side * tranche
        action = "DIRECT_NET_FLIP_1BAR_PAPER"
    return target, action


def run_v21_quote_paper_v1(
    quotes: Sequence[Quote30V1], *, seconds: int,
    market: str = "US Tech 100 NAS", observed_through: datetime,
    tranche: float = .01, max_inventory: float = .03,
    reversal_mode: str = "flat_first",
    hypothetical_latency_seconds: int = 0,
) -> PaperResult30V1:
    """Deterministic bid/ask scenario replay with no API calls or live writes.

    No 'profit' is reported as complete if any test segment ends with an open
    position. Such positions are instead separately marked at liquidation-side
    quotes, NOT asserted to have been closed at that price.
    """
    if reversal_mode not in ("flat_first", "direct_1bar"):
        raise ValueError("only controlled native and PAPER immediate-net flip")
    if hypothetical_latency_seconds not in (0, 1, 3, 5):
        raise ValueError("unsupported latency scenario")
    bars = build_completed_bars_v1(
        quotes, interval_seconds=seconds, market=market,
        observed_through=observed_through,
    )
    segments = _contiguous(bars, seconds)
    stamp = [q.at for q in quotes]
    settings = MacdTrailingConfigV3(tranche=tranche, max_inventory=max_inventory)
    completed_cash = 0.
    unrealized = 0.
    all_actions: list[PaperFill30V1] = []
    marks: list[float] = []
    skipped = modeled = incomplete = 0
    last_at = None
    assessed = 0
    running_mark = 0.
    for segment in segments:
        if len(segment) < MIN_SEGMENT_BARS:
            continue
        full_bars = tuple(x.bar for x in segment)
        observations = _macd_observations_native(full_bars)
        by_time = {x.bar_time.isoformat(): x for x in observations}
        position = 0.
        local_cash = 0.
        local_skipped = 0
        local_modeled = 0
        local_marks: list[float] = []
        local_last = None
        for i in range(1, len(segment)):
            item = segment[i]
            ob = by_time.get(item.bar.bar_time)
            prior = by_time.get(segment[i-1].bar.bar_time)
            if ob is None or prior is None:
                continue
            # Same time-of-day warmup for all 15s/30s/60s candidates,
            # despite the differing fixed MACD periods (bars vs minutes).
            segment_start = _utc(segment[0].bar.bar_time)
            if (item.closed_at - segment_start).total_seconds() < COMMON_WARMUP_SECONDS:
                continue
            # Signal computed from fully CLOSED prior bars, but fill can
            # only use a NEW actual quote at/after end + latency.
            end = item.closed_at
            # The last candle constituent may arrive AFTER the bar boundary.
            # Never place a simulated order using a quote that the collector
            # could not yet have seen. A next-quote response is still NOT a
            # genuine Saxo order latency/fill model.
            last_in_bar = bisect_left(stamp, end) - 1
            ready = max(end, quotes[last_in_bar].received_at)
            seek = ready + timedelta(seconds=hypothetical_latency_seconds)
            k = bisect_left(stamp, seek)
            if k >= len(quotes):
                local_skipped += 1
                continue
            quote = quotes[k]
            if (quote.at - ready).total_seconds() > (
                MAX_QUOTE_AGE_SECONDS + hypothetical_latency_seconds
            ):
                local_skipped += 1
                continue
            decision = macd_stoch_v21_target_v3(
                current_target=TargetInventoryV3(position),
                observation=ob, previous_observation=prior,
                bars=full_bars[:i+1], config=settings,
            )
            local_modeled += 1
            new_pos, action = _hypothetical_target(
                decision, position, reversal_mode=reversal_mode,
                tranche=tranche,
            )
            delta = round(new_pos - position, 10)
            if abs(delta) > 1.e-9:
                price = quote.ask if delta > 0 else quote.bid
                local_cash -= delta * price
                before = position
                position = new_pos
                all_actions.append(PaperFill30V1(
                    quote.received_at.isoformat(), item.bar.bar_time, action,
                    before, position, price, quote.bid, quote.ask,
                    _mark(local_cash, position, quote),
                ))
            local_marks.append(_mark(local_cash, position, quote))
            local_last = quote.received_at.isoformat()
        if not local_modeled:
            continue
        assessed += 1
        modeled += local_modeled
        skipped += local_skipped
        last_at = local_last
        if abs(position) > 1.e-9:
            incomplete += 1
            # Do not drop losing/open segments from the comparison. Mark at
            # last genuine BBO before the final eligible bar close, not
            # a fabricated broker liquidation/fill.
            close_time = segment[-1].closed_at
            q_idx = bisect_left(stamp, close_time) - 1
            final_quote = quotes[q_idx] if q_idx >= 0 else None
            local_final = (_mark(local_cash, position, final_quote)
                           if final_quote is not None else local_cash)
            unrealized += local_final
        else:
            completed_cash += local_cash
            local_final = local_cash
        marks.extend([running_mark + x for x in local_marks])
        running_mark += local_final
    if not assessed or not marks:
        pnl = dd = None
    else:
        # PNL withheld on unliquidated segments; descriptive mark reported
        # distinctly with no claim that the reset was executable.
        pnl = completed_cash if incomplete == 0 else None
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
        reversal_mode, hypothetical_latency_seconds,
        incomplete, unrealized, completed_cash,
    )
