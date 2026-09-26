"""Hunter: causal bid/ask price impulse policy; no broker order authority.

Feed one ordered, tradable quote at a time. This module never submits an order.
Parameters are provisional and must be calibrated against recorded tick data.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite


@dataclass(frozen=True, slots=True)
class HunterConfig:
    lookback_seconds: float = 8.0
    minimum_impulse_points: float = 8.0
    spread_multiplier: float = 4.0
    maximum_spread_points: float = 5.0
    exhaustion_seconds: float = 3.0
    exit_retrace_fraction: float = 0.08
    retrace_fraction: float = 0.15
    minimum_retrace_points: float = 1.5
    cooldown_seconds: float = 3.0
    maximum_gap_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class HunterDecision:
    target: str
    reason: str
    price: float
    at: datetime


@dataclass(slots=True)
class Hunter:
    config: HunterConfig = field(default_factory=HunterConfig)
    target: str = "FLAT"
    samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    impulse_origin: float | None = None
    extreme: float | None = None
    last_extreme_at: datetime | None = None
    last_exit_at: datetime | None = None
    resume_direction: str | None = None
    resume_extreme: float | None = None
    resume_origin: float | None = None
    resume_worst: float | None = None

    def on_quote(self, at: datetime, bid: float, ask: float) -> HunterDecision | None:
        if at.tzinfo is None:
            raise ValueError("Hunter requires timezone-aware timestamps")
        at = at.astimezone(timezone.utc)
        bid, ask = float(bid), float(ask)
        if not all(map(isfinite, (bid, ask))) or bid <= 0 or ask < bid:
            raise ValueError("Hunter requires valid bid/ask prices")
        spread = ask - bid
        mid = (bid + ask) / 2.0
        cfg = self.config
        if self.samples and at <= self.samples[-1][0]:
            return None  # Stale/out-of-order data must never produce an order.
        if self.samples and (at - self.samples[-1][0]).total_seconds() > cfg.maximum_gap_seconds:
            self.samples.clear()
            self.resume_direction = None
            if self.target != "FLAT":
                # Preserve target: absence of quotes is not evidence of a fill.
                self.samples.append((at, mid))
                return None
        self.samples.append((at, mid))
        while self.samples and (at - self.samples[0][0]).total_seconds() > cfg.lookback_seconds:
            self.samples.popleft()
        if spread > cfg.maximum_spread_points:
            return None

        if self.target != "FLAT":
            direction = 1 if self.target == "LONG" else -1
            assert self.extreme is not None and self.impulse_origin is not None
            favourable = mid > self.extreme if direction == 1 else mid < self.extreme
            if favourable:
                self.extreme, self.last_extreme_at = mid, at
                return None
            assert self.last_extreme_at is not None
            travelled = abs(self.extreme - self.impulse_origin)
            retrace = direction * (self.extreme - mid)
            threshold = max(cfg.minimum_retrace_points, cfg.exit_retrace_fraction * travelled)
            if retrace >= threshold and (at - self.last_extreme_at).total_seconds() >= cfg.exhaustion_seconds:
                previous = self.target
                self.target = "FLAT"
                self.last_exit_at = at
                self.resume_direction = previous
                self.resume_extreme = self.extreme
                self.resume_origin = self.impulse_origin
                self.resume_worst = mid
                return HunterDecision("FLAT", "IMPULSE_EXHAUSTED", mid, at)
            return None

        if self.last_exit_at and (at - self.last_exit_at).total_seconds() < cfg.cooldown_seconds:
            return None
        if self.resume_direction:
            assert self.resume_extreme is not None and self.resume_origin is not None
            direction = 1 if self.resume_direction == "LONG" else -1
            self.resume_worst = (min(self.resume_worst, mid) if direction == 1
                                 else max(self.resume_worst, mid))
            original_move = abs(self.resume_extreme - self.resume_origin)
            pullback = direction * (self.resume_extreme - self.resume_worst)
            if pullback >= cfg.retrace_fraction * original_move:
                self.resume_direction = None  # Deep pullback: fresh impulse required.
                self.samples.clear()
                self.samples.append((at, mid))
                return None
            elif direction * (mid - self.resume_extreme) > spread:
                self.target = self.resume_direction
                self.impulse_origin = self.resume_worst
                self.extreme = mid
                self.last_extreme_at = at
                self.resume_direction = None
                return HunterDecision(self.target, "SHALLOW_PULLBACK_NEW_EXTREME", mid, at)
            else:
                return None

        if len(self.samples) < 2:
            return None
        delta = mid - self.samples[0][1]
        threshold = max(cfg.minimum_impulse_points, cfg.spread_multiplier * spread)
        if abs(delta) < threshold:
            return None
        self.target = "LONG" if delta > 0 else "SHORT"
        self.impulse_origin = self.samples[0][1]
        self.extreme = mid
        self.last_extreme_at = at
        return HunterDecision(self.target, "PRICE_IMPULSE", mid, at)
