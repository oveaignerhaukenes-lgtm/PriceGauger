"""One-sided 1s Tech100 impulse signal, shared by PAPER replay and V3 LIVE.

No broker access, money management, time-based forced profit taking, or
account-loss threshold. Prices must be genuine ordered Saxo bid/ask quotes.
The trigger is relative to the *previously observed* 10s quote volatility;
no future candles, daily outcomes or post-event prices enter a decision.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median


@dataclass(frozen=True, slots=True)
class ImpulseCatcherConfig:
    side: str = "LONG"
    # A 3s trigger catches abrupt bursts; 10s is a separate slower arm.
    windows_seconds: tuple[int, ...] = (3, 10)
    history_seconds: int = 150
    min_impulse_points: float = 9.0
    relative_impulse_multiple: float = 3.0
    minimum_directional_efficiency: float = 0.78
    maximum_spread_points: float = 5.0
    spread_impulse_multiple: float = 4.0
    quote_gap_seconds: float = 4.0
    exhaustion_seconds: float = 2.0
    minimum_retrace_points: float = 3.0
    retrace_fraction: float = 0.20
    urgent_retrace_points: float = 12.0
    cooldown_seconds: float = 5.0

    def __post_init__(self):
        if self.side not in ("LONG", "SHORT"):
            raise ValueError("Impulse Catcher is strictly one-sided")
        if (not self.windows_seconds or any(w < 3 for w in self.windows_seconds)
                or self.history_seconds < 5*max(self.windows_seconds)):
            raise ValueError("Invalid observed lookback")
        if not 0 < self.minimum_directional_efficiency <= 1:
            raise ValueError("Invalid directionality")


@dataclass(frozen=True, slots=True)
class ImpulseCatcherDecision:
    target: str
    reason: str
    price: float
    at: datetime
    trigger_points: float = 0.0
    baseline_points: float = 0.0
    window_seconds: int = 0


@dataclass(slots=True)
class ImpulseCatcher:
    config: ImpulseCatcherConfig = field(default_factory=ImpulseCatcherConfig)
    target: str = "FLAT"
    samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    entry_mid: float | None = None
    extreme: float | None = None
    last_extreme_at: datetime | None = None
    last_exit_at: datetime | None = None

    def on_quote(self, at: datetime, bid: float, ask: float) -> ImpulseCatcherDecision | None:
        if at.tzinfo is None:
            raise ValueError("Timezone-aware quote timestamp required")
        at = at.astimezone(timezone.utc)
        bid, ask = float(bid), float(ask)
        if not(isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
            raise ValueError("Invalid Saxo bid/ask")
        if self.samples and at <= self.samples[-1][0]:
            return None
        cfg=self.config
        mid = (bid+ask)/2
        spread = ask-bid
        if self.samples and (at-self.samples[-1][0]).total_seconds()>cfg.quote_gap_seconds:
            self.samples.clear()
            self.samples.append((at,mid))
            if self.target != "FLAT":
                self.target="FLAT"
                self.last_exit_at=at
                self.entry_mid=self.extreme=None
                self.last_extreme_at=None
                return ImpulseCatcherDecision("FLAT","QUOTE_GAP_FLAT",mid,at)
            return None
        self.samples.append((at,mid))
        while self.samples and (at-self.samples[0][0]).total_seconds()>cfg.history_seconds:
            self.samples.popleft()
        direction = 1 if cfg.side == "LONG" else -1

        # Managing an existing position is allowed even when the spread widens;
        # widening spread must never make us *open* a fresh position.
        if self.target != "FLAT":
            if self.extreme is None:
                self.extreme=mid
                self.last_extreme_at=at
            if direction*(mid-self.extreme)>0:
                self.extreme=mid
                self.last_extreme_at=at
                return None
            if self.last_extreme_at is None:
                self.last_extreme_at=at
            entry = self.entry_mid if self.entry_mid is not None else mid
            travelled = max(0., direction*(self.extreme-entry))
            retrace = direction*(self.extreme-mid)
            threshold = max(cfg.minimum_retrace_points,
                            cfg.retrace_fraction*travelled,2*spread)
            urgent = max(cfg.urgent_retrace_points,0.35*travelled,3*spread)
            stalled = (at-self.last_extreme_at).total_seconds()>=cfg.exhaustion_seconds
            # A real reversal must not wait several completed minute bars.
            if retrace>=urgent or (retrace>=threshold and stalled):
                self.target="FLAT"
                self.last_exit_at=at
                self.entry_mid=self.extreme=None
                self.last_extreme_at=None
                return ImpulseCatcherDecision("FLAT","IMPULSE_EXHAUSTED",mid,at)
            return None

        if spread>cfg.maximum_spread_points:
            return None
        if self.last_exit_at and (at-self.last_exit_at).total_seconds()<cfg.cooldown_seconds:
            return None
        # Examine the quickest window first. Both use only historic quotes;
        # each reference ends BEFORE that window to avoid lookahead.
        for window in cfg.windows_seconds:
            window_start = at-timedelta(seconds=window)
            recent = [(t,p) for t,p in self.samples if t>=window_start]
            if len(recent)<3 or (at-recent[0][0]).total_seconds()<window-1:
                continue
            delta = direction*(mid-recent[0][1])
            travel = sum(abs(b[1]-a[1]) for a,b in zip(recent,recent[1:]))
            efficiency = delta/travel if travel>0 else 0.
            if delta<=0 or efficiency<cfg.minimum_directional_efficiency:
                continue
            older = [(t,p) for t,p in self.samples if t<window_start]
            historical = []
            for i in range(1,len(older),max(1,window//2)):
                end_t,end_p = older[i]
                reference = next(((t,p) for t,p in reversed(older[:i])
                                  if window-1 <= (end_t-t).total_seconds() <= window+1),None)
                if reference is not None:
                    historical.append(abs(end_p-reference[1]))
            if len(historical)<5:
                continue
            baseline = median(historical)
            threshold = max(cfg.min_impulse_points,cfg.spread_impulse_multiple*spread,
                            cfg.relative_impulse_multiple*baseline)
            if delta>=threshold:
                self.target = cfg.side
                self.entry_mid = self.extreme = mid
                self.last_extreme_at = at
                return ImpulseCatcherDecision(cfg.side,"QUALIFIED_IMPULSE",mid,at,
                                              round(delta,4),round(baseline,4),window)
        return None
