"""Causal, quote-executable PAPER replay for the Tech100 one-sided catchers.

Signals are computed on an observed Saxo quote, while PAPER fills occur on
the NEXT valid quote, at the displayed ask/bid. These are NOT Saxo fills.
An unfilled order, a feed gap and an open end-of-sample position are never
credited as realized profit. Any broker latency beyond the next quote is
unmodelled and must be compared prospectively with real reconciliations.
"""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median
from typing import Callable

from autotrader_impulse_catcher_v1 import (
    ImpulseCatcher, ImpulseCatcherConfig, ImpulseCatcherDecision,
)


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
    entry_trigger_points: float = 0.0
    entry_window_seconds: int = 0
    entry_signal_mid: float = 0.0


@dataclass(frozen=True, slots=True)
class ImpulsePaperResult:
    side: str
    quotes: int
    signals: int
    unfilled_entries: int
    unfilled_exits: int
    unfinished_positions: int
    trades: tuple[ImpulsePaperTrade, ...]
    blocked_entries: int = 0

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
    exit_config_asof: Callable[[datetime], ImpulseCatcherConfig] | None = None,
    entry_allowed_asof: Callable[[ImpulseCatcherDecision], bool] | None = None,
) -> ImpulsePaperResult:
    """Replay with separate signal vs next-quote execution clocks.

    An optional PAPER-only as-of callback can alter *exit* thresholds on each
    quote. An optional PAPER entry gate can veto an already-qualified impulse,
    resetting the hypothetical signal engine to FLAT with a normal 5s cooldown.
    It must never suppress FLAT or a broker safety exit. LIVE uses neither hook.
    """
    if max_fill_delay_s<=0:
        raise ValueError("PAPER fill delay limit must be positive")
    model=ImpulseCatcher(config)
    trades=[]
    open_trade=None
    awaiting_entry=None
    awaiting_exit=None
    signals=missed_entries=missed_exits=blocked_entries=0
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
                            "entry_delay":delay,"entry_trigger_points":signal.trigger_points,
                            "entry_window_seconds":signal.window_seconds,
                            "entry_signal_mid":signal.price}
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
                    entry_delay_s=open_trade["entry_delay"],exit_delay_s=delay,
                    entry_trigger_points=open_trade["entry_trigger_points"],
                    entry_window_seconds=open_trade["entry_window_seconds"],
                    entry_signal_mid=open_trade["entry_signal_mid"]))
                open_trade=None
            else:
                missed_exits+=1
                # A failed close is not a realized PAPER gain. Account for
                # remaining unmatched exposure and require manual review.
                break
        if exit_config_asof is not None:
            candidate=exit_config_asof(q.at)
            if not isinstance(candidate,ImpulseCatcherConfig):
                raise ValueError("Exit policy must return an ImpulseCatcherConfig")
            for name in (
                "side", "windows_seconds", "history_seconds", "min_impulse_points",
                "relative_impulse_multiple", "minimum_directional_efficiency",
                "maximum_spread_points", "spread_impulse_multiple",
                "quote_gap_seconds", "minimum_retrace_points", "retrace_fraction",
                "urgent_retrace_points", "cooldown_seconds",
            ):
                if getattr(candidate,name)!=getattr(config,name):
                    raise ValueError("PAPER exit policy cannot change "+name)
            model.config=candidate
        decision=model.on_quote(q.at,q.bid,q.ask)
        if decision is None:
            continue
        if decision.target==config.side:
            signals+=1
            if open_trade is None and awaiting_entry is None:
                allowed=entry_allowed_asof(decision) if entry_allowed_asof is not None else True
                if type(allowed) is not bool:
                    raise ValueError("PAPER entry policy must return bool")
                if allowed:
                    awaiting_entry=decision
                else:
                    blocked_entries+=1
                    # The order was never submitted. Do not simulate a position
                    # (or its exit) inside the signal engine. Rate-limit identical
                    # vetoes using the unchanged engine cooldown, not a broker call.
                    model.target="FLAT"
                    model.entry_mid=model.extreme=None
                    model.last_extreme_at=None
                    model.last_exit_at=q.at
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
                              missed_exits,int(open_trade is not None),tuple(trades),
                              blocked_entries)


def summarize_impulse_replay(result: ImpulsePaperResult) -> dict[str, float | int | None]:
    """Metrics in *index points*, not account NAV or leveraged NOK returns."""
    return {
        "signals":result.signals,"completed":len(result.trades),
        "blocked_entries":result.blocked_entries,
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


def entry_regime_asof(
    quotes: tuple[ImpulseQuote, ...],at: datetime,
    *, quote_times: tuple[datetime, ...] | None = None,
) -> str:
    """Predefined causal 60s price-path-efficiency bucket; never post-entry data.

    Requires observed 1s BBO with sufficient contiguous coverage. Buckets are
    descriptive research hypotheses, not evidence of a price forecast.
    """
    if not quotes:
        return "UKJENT"
    stamps=quote_times if quote_times is not None else [q.at for q in quotes]
    until=bisect_right(stamps,at)
    first=bisect_right(stamps,at-timedelta(seconds=60),0,until)
    window=quotes[first:until]
    if (len(window)<30 or (window[-1].at-window[0].at).total_seconds()<45 or
        any((b.at-a.at).total_seconds()>8 for a,b in zip(window,window[1:]))):
        return "UKJENT"
    path=sum(abs(b.mid-a.mid) for a,b in zip(window,window[1:]))
    if path<=0:
        return "SIDEVEIS"
    efficiency=abs(window[-1].mid-window[0].mid)/path
    if efficiency>=0.55:
        return "TREND"
    if efficiency<=0.25:
        return "SIDEVEIS"
    return "BLANDET"
