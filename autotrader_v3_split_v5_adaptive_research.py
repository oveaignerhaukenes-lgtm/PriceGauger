"""Research-only V5: online loss feedback with quantized entry thresholds.

One instance per independent PAPER replay. Uses no future bar: the next-open
fill is first observed at that bar's close, and only *completed* trades change
the subsequent entry gate. This approximation assumes whole-position fills at
next minute open; it must NOT be connected to a LIVE worker without durable,
broker-reconciled executions, gap handling and restart recovery.

The underlying V3 always owns exits, including all hard risk/safety exits.
An adaptive gate can refuse OPEN/ADD; it cannot delay or override any FLAT.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _decision, _utc
from autotrader_v3_macd_stoch_v21_split_v3 import split_price_hist_regime_v3


@dataclass(frozen=True, slots=True)
class V5QuantizedState:
    losses_recent: int
    trades_recent: int
    momentum_atr: float
    directional_efficiency: float
    mode: str
    required_efficiency: float
    required_momentum_atr: float


@dataclass(frozen=True, slots=True)
class V5Policy:
    """Three coarse rules fixed *before* viewing chronological holdout results."""

    name: str = "adaptive"
    memory_trades: int = 3
    base_efficiency: float = .20
    after_one_loss_efficiency: float = .32
    after_two_losses_efficiency: float = .48
    base_momentum_atr: float = .30
    after_one_loss_momentum_atr: float = .70
    after_two_losses_momentum_atr: float = 1.15
    loss_memory_minutes: int = 35
    spread_bps_roundtrip: float = 4.

    def __post_init__(self):
        if not (self.memory_trades >= 1 and self.loss_memory_minutes >= 1
                and all(0 <= x <= 1 for x in (
                    self.base_efficiency, self.after_one_loss_efficiency,
                    self.after_two_losses_efficiency))
                and all(x >= 0 for x in (
                    self.base_momentum_atr, self.after_one_loss_momentum_atr,
                    self.after_two_losses_momentum_atr,
                    self.spread_bps_roundtrip))):
            raise ValueError("Invalid V5 bounded quantization")


POLICIES_V5 = (
    # Ablation: same entry quantization, but never tightens after losses.
    V5Policy(name="fixed", after_one_loss_efficiency=.20,
             after_two_losses_efficiency=.20,
             after_one_loss_momentum_atr=.30,
             after_two_losses_momentum_atr=.30),
    V5Policy(name="minimal", base_efficiency=.12,
             after_one_loss_efficiency=.18, after_two_losses_efficiency=.36,
             base_momentum_atr=.15, after_one_loss_momentum_atr=.40,
             after_two_losses_momentum_atr=.85),
    V5Policy(),
    V5Policy(name="cautious", base_efficiency=.30,
             after_one_loss_efficiency=.45, after_two_losses_efficiency=.60,
             base_momentum_atr=.55, after_one_loss_momentum_atr=.90,
             after_two_losses_momentum_atr=1.40),
)


def quantized_state_v5(*, source_bars, cutoff, market_name: str,
                        side: int, losses_recent: int,
                        trades_recent: int, policy: V5Policy):
    """Compute directional efficiency and ATR from completed contiguous 1m.

    12m net movement / travelled distance: 0=chop, 1=one-way movement.
    6m signed return / 14-bar prior true range approximates current pace.
    The bins are set by *past* closed-trade losses, never future P/L.
    """
    history = _completed_bars(source_bars, timeframe=1,
                              cutoff=cutoff, market=market_name)
    if len(history) < 19:
        return None
    bars = history[-19:]
    if any(_utc(b.bar_time) - _utc(a.bar_time) != timedelta(minutes=1)
           for a, b in zip(bars, bars[1:])):
        return None
    closes = tuple(float(bar.close) for bar in bars)
    if not all(isfinite(x) and x > 0 for x in closes):
        return None
    travel = sum(abs(a-b) for a, b in zip(closes[-13:-1], closes[-12:]))
    efficiency = (abs(closes[-1]-closes[-13])/travel if travel > 1e-9 else 0.)
    tr = [max(float(b.high)-float(b.low),
              abs(float(b.high)-closes[i-1]), abs(float(b.low)-closes[i-1]))
          for i, b in enumerate(bars) if i >= 1]
    atr = sum(tr[-14:]) / 14
    if atr <= 1e-9 or not isfinite(atr):
        return None
    momentum = side * (closes[-1] - closes[-7]) / atr
    loss_bin = min(2, max(0, int(losses_recent)))
    efficiency_min = (
        policy.base_efficiency, policy.after_one_loss_efficiency,
        policy.after_two_losses_efficiency)[loss_bin]
    momentum_min = (
        policy.base_momentum_atr, policy.after_one_loss_momentum_atr,
        policy.after_two_losses_momentum_atr)[loss_bin]
    mode = "loss_defensive" if loss_bin == 2 else (
        "loss_cautious" if loss_bin == 1 else "normal")
    return V5QuantizedState(losses_recent, trades_recent, momentum,
                            efficiency, mode, efficiency_min, momentum_min)


class AdaptiveV5Paper:
    """Local stateful research agent; instantiate fresh for each replay day.

    Tracks completed *simulated* round trips at next-bar open. The assumption
    matches the Strategy Lab replay for all-or-nothing OPEN/FLAT but not partial
    reduction, broker fills, overnight gaps or latency. Account risk is not
    inferred from this study.
    """

    def __init__(self, *, side: int, policy: V5Policy = V5Policy(),
                 base_strategy=split_price_hist_regime_v3):
        if side not in (-1, 1):
            raise ValueError("side must be +1 or -1")
        self.side = side
        self.policy = policy
        self.base_strategy = base_strategy
        self._amount = 0.
        self._average_price = None
        self._realized = deque(maxlen=policy.memory_trades)
        self._last_loss_at = None
        self._last_bar = None
        self._last_market = None
        self.states = []
        self.gates = 0
        self.paper_round_trips = 0

    def _reset(self):
        self._amount = 0.
        self._average_price = None
        self._realized.clear()
        self._last_loss_at = None

    def __call__(self, *, current_target, observation,
                 source_bars=(), market_name="", **kwargs):
        cutoff = _utc(getattr(observation, "closed_at", observation.bar_time))
        history = _completed_bars(source_bars, timeframe=1,
                                  cutoff=cutoff, market=market_name)
        if not history:
            return self.base_strategy(
                side=self.side, current_target=current_target,
                observation=observation, source_bars=source_bars,
                market_name=market_name, **kwargs)
        latest = history[-1]
        observed_close = _utc(latest.bar_time) + timedelta(minutes=1)
        if observed_close != cutoff:
            raise ValueError("Research V5 requires completed current minute")
        if (self._last_bar is not None and
                (cutoff-self._last_bar != timedelta(minutes=1)
                 or market_name != self._last_market)):
            self._reset()
        if self._last_bar is not None and cutoff <= self._last_bar:
            raise ValueError("Research V5 observations must advance")
        self._last_bar, self._last_market = cutoff, market_name

        current = float(current_target.amount)
        if self.side * current < -1e-9:
            self._reset()  # V3 will enforce WRONG_SIDE_FLAT.
        elif current != self._amount:
            fill_open = float(latest.open)
            if self._amount == 0. and current:
                self._average_price = fill_open
            elif current == 0. and self._amount:
                if self._average_price is not None:
                    gross = self.side * (fill_open-self._average_price)
                    round_trip_cost = (fill_open+self._average_price) * (
                        self.policy.spread_bps_roundtrip / 20000)
                    net = gross-round_trip_cost
                    self._realized.append(net)
                    self.paper_round_trips += 1
                    if net < 0:
                        self._last_loss_at = cutoff
                self._average_price = None
            elif self._average_price is not None and abs(current) > abs(self._amount):
                self._average_price = (
                    abs(self._amount)*self._average_price +
                    (abs(current)-abs(self._amount))*fill_open) / abs(current)
            self._amount = current

        original = self.base_strategy(
            side=self.side, current_target=current_target,
            observation=observation, source_bars=source_bars,
            market_name=market_name, **kwargs)
        # Fading memory: old losses cannot keep entry requirements elevated
        # forever after a market pattern changes. This is *not* P/L relabeling.
        if (self._last_loss_at is not None and
                cutoff-self._last_loss_at > timedelta(minutes=self.policy.loss_memory_minutes)):
            self._realized.clear()
            self._last_loss_at = None
        loss_count = sum(net < 0 for net in self._realized)
        state = quantized_state_v5(
            source_bars=source_bars, cutoff=cutoff, market_name=market_name,
            side=self.side, losses_recent=loss_count,
            trades_recent=len(self._realized), policy=self.policy)
        if state is not None:
            self.states.append((cutoff, state))
        # Reject only new exposure. Existing positions can always reduce or
        # flatten via V3, even in the highest loss bin.
        proposed = float(original.target.amount)
        if (state is not None and self.side * proposed > self.side * current+1e-9
                and (state.directional_efficiency < state.required_efficiency
                     or state.momentum_atr < state.required_momentum_atr)):
            self.gates += 1
            return _decision(
                amount=current, action="V5_QUANTIZED_ENTRY_GUARD",
                reason=(f"PAPER-only loss-bin={min(2,loss_count)}; "
                        f"eff={state.directional_efficiency:.2f}/"
                        f"{state.required_efficiency:.2f}, "
                        f"signed6m/ATR={state.momentum_atr:.2f}/"
                        f"{state.required_momentum_atr:.2f}"),
                observation=observation, base=original)
        return original


__all__ = ["AdaptiveV5Paper", "V5Policy", "POLICIES_V5",
           "V5QuantizedState", "quantized_state_v5"]
