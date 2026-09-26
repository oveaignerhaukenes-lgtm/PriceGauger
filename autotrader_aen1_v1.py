"""Aen#1: closed 1m price breakout with trend alignment and a cost buffer.

Research/shadow only. The policy accepts only contiguous completed bars and
contains no Saxo client, strategy enrollment or order submission.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite


STRATEGY_KEY = "aen-1-price-breakout-shadow-v1"
SERIES_VERSION = "AEN1-PRICE-1M-TREND-EXIT-COST-v1"


@dataclass(frozen=True, slots=True)
class Aen1Config:
    trend_minutes: int = 60
    breakout_minutes: int = 12
    impulse_minutes: int = 3
    noise_minutes: int = 20
    minimum_efficiency: float = 0.28
    minimum_local_efficiency: float = 0.45
    assumed_spread_points: float = 2.0  # research assumption, not broker quote
    cooldown_minutes: int = 5


@dataclass(frozen=True, slots=True)
class Aen1Decision:
    at: datetime
    target: str
    reason: str
    price: float


@dataclass(slots=True)
class Aen1:
    config: Aen1Config = field(default_factory=Aen1Config)
    state: str = "FLAT"
    prices: deque[float] = field(default_factory=deque)
    last_at: datetime | None = None
    entry_price: float | None = None
    best_price: float | None = None
    last_exit_at: datetime | None = None

    def on_close(self, at: datetime, price: float) -> Aen1Decision | None:
        if at.tzinfo is None:
            raise ValueError("closed bar time must be timezone aware")
        at = at.astimezone(timezone.utc)
        price = float(price)
        if not isfinite(price) or price <= 0:
            raise ValueError("price must be positive and finite")
        if self.last_at is not None and at <= self.last_at:
            return None
        if self.last_at is not None and at - self.last_at != timedelta(minutes=1):
            # No invented returns or decisions across gaps/market closure.
            self.prices.clear()
            self.last_at = at
            self.prices.append(price)
            if self.state != "FLAT":
                self.state, self.entry_price, self.best_price = "FLAT", None, None
                self.last_exit_at = at
                return Aen1Decision(at, "FLAT", "DATA_GAP", price)
            return None
        self.last_at = at
        cfg = self.config
        previous = tuple(self.prices)
        self.prices.append(price)
        while len(self.prices) > cfg.trend_minutes + 1:
            self.prices.popleft()
        if len(previous) < cfg.trend_minutes:
            return None

        recent = previous[-cfg.noise_minutes:]
        noise = sorted(abs(b - a) for a, b in zip(recent, recent[1:]))
        if not noise:
            return None
        typical_move = noise[len(noise) // 2]
        spread = cfg.assumed_spread_points
        trend_change = price - previous[-cfg.trend_minutes]
        travel = sum(abs(b - a) for a, b in zip(previous[-cfg.trend_minutes:],
                                                  (*previous[-cfg.trend_minutes + 1:], price)))
        efficiency = abs(trend_change) / travel if travel > 0 else 0.0
        trend = (1 if trend_change > 0 else -1) if (
            efficiency >= cfg.minimum_efficiency and abs(trend_change) >= max(3 * typical_move, 3 * spread)
        ) else 0

        if self.state != "FLAT":
            direction = 1 if self.state == "LONG" else -1
            assert self.entry_price is not None and self.best_price is not None
            self.best_price = max(self.best_price, price) if direction > 0 else min(self.best_price, price)
            favourable = max(0.0, direction * (self.best_price - self.entry_price))
            retrace = direction * (self.best_price - price)
            if (trend == -direction or
                retrace >= max(2 * spread, 2 * typical_move, favourable * 0.35)):
                self.state, self.entry_price, self.best_price = "FLAT", None, None
                self.last_exit_at = at
                return Aen1Decision(at, "FLAT", "TREND_LOST" if trend == -direction else "TRAILING_EXIT", price)
            return None

        if self.last_exit_at and (at - self.last_exit_at).total_seconds() < cfg.cooldown_minutes * 60:
            return None
        lookback = previous[-cfg.breakout_minutes:]
        short = (*previous[-cfg.breakout_minutes:], price)
        local_travel = sum(abs(b - a) for a, b in zip(short, short[1:]))
        local_efficiency = abs(price - short[0]) / local_travel if local_travel else 0.0
        impulse = price - previous[-cfg.impulse_minutes]
        hurdle = max(3 * spread, 2 * typical_move)
        if local_efficiency < cfg.minimum_local_efficiency or abs(impulse) < hurdle:
            return None
        direction = 1 if price > max(lookback) else -1 if price < min(lookback) else 0
        if direction == 0 or (trend and direction != trend):
            return None
        self.state = "LONG" if direction > 0 else "SHORT"
        self.entry_price = self.best_price = price
        return Aen1Decision(at, self.state, "PRICE_BREAKOUT", price)
