"""Rabid Dog: bid/ask directional-change shadow, without order authority.

The 100/hour budget is a rolling cap on *hypothetical* order requests, not a
target. Direct reversals count as one order, with twice the position amount.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite


STRATEGY_KEY = "rabid-dog-price-chase-shadow-v1"


@dataclass(frozen=True, slots=True)
class RabidDogConfig:
    units: float = 0.01
    orders_per_hour: int = 100
    minimum_order_interval_seconds: float = 1.0
    maximum_quote_gap_seconds: float = 5.0
    minimum_move_points: float = 3.0
    spread_multiplier: float = 3.0
    noise_multiplier: float = 3.0
    noise_samples: int = 20
    maximum_spread_points: float = 5.0


@dataclass(frozen=True, slots=True)
class RabidDogDecision:
    at: datetime
    target: str
    reason: str
    order_amount: float
    orders_last_hour: int
    realized_points: float
    unrealized_points: float


@dataclass(slots=True)
class RabidDog:
    config: RabidDogConfig = field(default_factory=RabidDogConfig)
    target: str = "FLAT"
    last_at: datetime | None = None
    last_mid: float | None = None
    anchor: float | None = None
    extreme: float | None = None
    entry_price: float | None = None
    realized_points: float = 0.0
    recent_moves: deque[float] = field(default_factory=deque)
    order_times: deque[datetime] = field(default_factory=deque)

    def _budget(self, at: datetime) -> int:
        while self.order_times and at - self.order_times[0] >= timedelta(hours=1):
            self.order_times.popleft()
        return len(self.order_times)

    def _unrealized(self, bid: float, ask: float) -> float:
        if self.target == "LONG":
            return bid - self.entry_price
        if self.target == "SHORT":
            return self.entry_price - ask
        return 0.0

    def on_quote(self, at: datetime, bid: float, ask: float) -> RabidDogDecision | None:
        if at.tzinfo is None:
            raise ValueError("quote timestamps must be timezone aware")
        at = at.astimezone(timezone.utc)
        bid, ask = float(bid), float(ask)
        if not all(map(isfinite, (bid, ask))) or bid <= 0 or ask < bid:
            raise ValueError("valid bid/ask required")
        if self.last_at is not None and at <= self.last_at:
            return None
        cfg = self.config
        mid = (bid + ask) / 2
        spread = ask - bid
        used = self._budget(at)
        gap = self.last_at is not None and (at - self.last_at).total_seconds() > cfg.maximum_quote_gap_seconds
        interval_ok = not self.order_times or (at - self.order_times[-1]).total_seconds() >= cfg.minimum_order_interval_seconds
        prior_mid = self.last_mid
        self.last_at, self.last_mid = at, mid

        if gap:
            self.anchor = self.extreme = mid
            self.recent_moves.clear()
            if self.target != "FLAT" and used < cfg.orders_per_hour and interval_ok:
                return self._change(at, "FLAT", "QUOTE_GAP", bid, ask)
            return None
        if prior_mid is None:
            self.anchor = self.extreme = mid
            return None
        self.recent_moves.append(abs(mid - prior_mid))
        while len(self.recent_moves) > cfg.noise_samples:
            self.recent_moves.popleft()
        if spread > cfg.maximum_spread_points or not interval_ok:
            return None
        if used >= cfg.orders_per_hour:
            return None
        # Keep the 100th potential order available to flatten, including if
        # a large reversal arrives while the hourly budget is almost spent.
        if used >= cfg.orders_per_hour - 1:
            return (self._change(at, "FLAT", "ORDER_BUDGET_RESERVED", bid, ask)
                    if self.target != "FLAT" else None)

        moves = sorted(self.recent_moves)
        typical = moves[len(moves) // 2] if len(moves) >= 5 else 0.0
        threshold = max(cfg.minimum_move_points, cfg.spread_multiplier * spread,
                        cfg.noise_multiplier * typical)
        if self.target == "LONG":
            self.extreme = max(self.extreme, mid)
            if self.extreme - mid >= threshold:
                return self._change(at, "SHORT", "DOWN_DIRECTIONAL_CHANGE", bid, ask)
        elif self.target == "SHORT":
            self.extreme = min(self.extreme, mid)
            if mid - self.extreme >= threshold:
                return self._change(at, "LONG", "UP_DIRECTIONAL_CHANGE", bid, ask)
        else:
            assert self.anchor is not None
            if mid - self.anchor >= threshold:
                return self._change(at, "LONG", "UP_DIRECTIONAL_CHANGE", bid, ask)
            if self.anchor - mid >= threshold:
                return self._change(at, "SHORT", "DOWN_DIRECTIONAL_CHANGE", bid, ask)
        return None

    def _change(self, at: datetime, target: str, reason: str, bid: float, ask: float) -> RabidDogDecision:
        previous = self.target
        if previous == "LONG":
            self.realized_points += bid - self.entry_price
        elif previous == "SHORT":
            self.realized_points += self.entry_price - ask
        self.target = target
        self.entry_price = ask if target == "LONG" else bid if target == "SHORT" else None
        self.extreme = (bid + ask) / 2
        self.anchor = self.extreme
        self.order_times.append(at)
        return RabidDogDecision(
            at=at, target=target, reason=reason,
            order_amount=cfg_units(self.config.units, previous, target),
            orders_last_hour=len(self.order_times),
            realized_points=self.realized_points,
            unrealized_points=self._unrealized(bid, ask),
        )


def cfg_units(units: float, previous: str, target: str) -> float:
    signed = {"SHORT": -1, "FLAT": 0, "LONG": 1}
    return abs(signed[target] - signed[previous]) * units
