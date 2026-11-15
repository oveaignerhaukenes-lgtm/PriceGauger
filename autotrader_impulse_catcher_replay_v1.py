"""Causal, quote-executable PAPER replay for the Tech100 one-sided catchers.

Signals are computed on an observed Saxo quote, while PAPER fills occur on
the NEXT valid quote, at the displayed ask/bid. These are NOT Saxo fills.
An unfilled order, a feed gap and an open end-of-sample position are never
credited as realized profit. Any broker latency beyond the next quote is
unmodelled and must be compared prospectively with real reconciliations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median

from autotrader_impulse_catcher_v1 import ImpulseCatcher, ImpulseCatcherConfig


@dataclass(frozen=True, slots=True)
class ImpulseQuote:
    at: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid+self.ask)/2


@dataclass(frozen=True, slots=True)
class ImpulsePaperTrade:
    side: str
    signal_at: datetime
    filled_at: datetime
    exit_signal_at: datetime
    exited_at: datetime
    fill_price: float
    exit_price: float
    gross_points: float
    max_favorable_points: float
    max_adverse_points: float
    entry_delay_s: float
    exit_delay_s: float


@dataclass(frozen=True, slots=True)
class ImpulsePaperResult:
    side: str
    quotes: int
    signals: int
    unfilled_entries: int
    unfilled_exits: int
    unfinished_positions: int
    trades: tuple[ImpulsePaperTrade, ...]

    @property
    def net_points(self) -> float:
        return sum(t.gross_points for t in self.trades)

    @property
    def win_fraction(self) -> float | None:
        return (sum(t.gross_points>0 for t in self.trades)/len(self.trades)
                if self.trades else None)

    @property
    def median_points(self) -> float | None:
        return median(t.gross_points for t in self.trades) if self.trades else None


def prepare_impulse_quotes(rows) -> tuple[ImpulseQuote, ...]:
    """Reject stale/invalid Saxo BBO, never invent quotes on an empty second."""
    result = []
    for row in rows:
        try:
            at = row["quote_at"] if isinstance(row["quote_at"], datetime) else datetime.fromisoformat(
                str(row["quote_at"]).replace("Z","+00:00"))
            received = row["received_at"] if isinstance(row["received_at"],datetime) else datetime.fromisoformat(
                str(row["received_at"]).replace("Z","+00:00"))
            if at.tzinfo is None or received.tzinfo is None:
                continue
            at=at.astimezone(timezone.utc)
            received=received.astimezone(timezone.utc)
            bid,ask=float(row["bid"]),float(row["ask"])
            if not (isfinite(bid) and isfinite(ask) and 0<bid<=ask
                    and -2<=(received-at).total_seconds()<=5):
                continue
            if result and at<=result[-1].at:
                continue
            result.append(ImpulseQuote(at,bid,ask))
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
    return tuple(result)


def replay_impulse_catcher(
    quotes: tuple[ImpulseQuote, ...],
    config: ImpulseCatcherConfig,
    *, max_fill_delay_s: float = 3.0,
) -> ImpulsePaperResult:
    """Replay with separate signal vs next-quote execution clocks."""
    if max_fill_delay_s<=0:
        raise ValueError("PAPER fill delay limit must be positive")
    model=ImpulseCatcher(config)
    trades=[]
    open_trade=None
    awaiting_entry=None
    awaiting_exit=None
    signals=missed_entries=missed_exits=0
    sign=1 if config.side=="LONG" else -1
    for q in quotes:
        # Previous quote's hypothetical order: never fill on trigger tick.
        if awaiting_entry is not None:
            signal=awaiting_entry
            delay=(q.at-signal.at).total_seconds()
            awaiting_entry=None
            if 0<delay<=max_fill_delay_s:
                price=q.ask if sign>0 else q.bid
                open_trade={"signal_at":signal.at,"filled_at":q.at,
                            "fill_price":price,"mfe":sign*((q.bid if sign>0 else q.ask)-price),
                            "mae":sign*((q.bid if sign>0 else q.ask)-price),
                            "entry_delay":delay}
            else:
                missed_entries+=1
        if open_trade is not None:
            closeable=q.bid if sign>0 else q.ask
            marked=sign*(closeable-open_trade["fill_price"])
            open_trade["mfe"]=max(open_trade["mfe"],marked)
            open_trade["mae"]=min(open_trade["mae"],marked)
        if awaiting_exit is not None:
            signal=awaiting_exit
            delay=(q.at-signal.at).total_seconds()
            awaiting_exit=None
            if open_trade is not None and 0<delay<=max_fill_delay_s:
                price=q.bid if sign>0 else q.ask
                trades.append(ImpulsePaperTrade(
                    side=config.side,signal_at=open_trade["signal_at"],
                    filled_at=open_trade["filled_at"],exit_signal_at=signal.at,
                    exited_at=q.at,fill_price=open_trade["fill_price"],
                    exit_price=price,
                    gross_points=sign*(price-open_trade["fill_price"]),
                    max_favorable_points=open_trade["mfe"],
                    max_adverse_points=open_trade["mae"],
                    entry_delay_s=open_trade["entry_delay"],exit_delay_s=delay))
                open_trade=None
            else:
                missed_exits+=1
                # A failed close is not a realized PAPER gain. Account for
                # remaining unmatched exposure and require manual review.
                break
        decision=model.on_quote(q.at,q.bid,q.ask)
        if decision is None:
            continue
        if decision.target==config.side:
            signals+=1
            if open_trade is None and awaiting_entry is None:
                awaiting_entry=decision
        elif decision.target=="FLAT":
            if awaiting_entry is not None:
                awaiting_entry=None
                missed_entries+=1
            elif open_trade is not None:
                awaiting_exit=decision
    if awaiting_entry is not None:
        missed_entries+=1
    if awaiting_exit is not None:
        missed_exits+=1
    return ImpulsePaperResult(config.side,len(quotes),signals,missed_entries,
                              missed_exits,int(open_trade is not None),tuple(trades))


def summarize_impulse_replay(result: ImpulsePaperResult) -> dict[str, float | int | None]:
    """Metrics in *index points*, not account NAV or leveraged NOK returns."""
    return {
        "signals":result.signals,"completed":len(result.trades),
        "unfilled_entries":result.unfilled_entries,
        "unfilled_exits":result.unfilled_exits,
        "unfinished_positions":result.unfinished_positions,
        "net_index_points":round(result.net_points,3),
        "win_pct":round(100*result.win_fraction,2) if result.win_fraction is not None else None,
        "median_points":round(result.median_points,3) if result.median_points is not None else None,
        "median_entry_delay_s":(round(median(t.entry_delay_s for t in result.trades),2)
                                if result.trades else None),
        "median_exit_delay_s":(round(median(t.exit_delay_s for t in result.trades),2)
                               if result.trades else None),
    }
