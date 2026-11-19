"""Research-only TECH100 four-channel synthesis.

Pure, broker-independent signal composition. This module never reads accounts,
changes instance settings, requests LLM calls or places Saxo orders. Directional
effects and confidence MUST originate from validated upstream forecasters; news
relevance alone is not a directional signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Mapping, Sequence

REGIME = "macro_regime"
IMPULSE = "cross_market_impulse"
TECH_NEWS = "tech_news"
MACRO_NEWS = "macro_news"
CHANNELS = (REGIME, IMPULSE, TECH_NEWS, MACRO_NEWS)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ChannelSignal:
    channel: str
    observed_at: datetime
    horizon_minutes: int
    expected_tech100_return_pct: float | None
    confidence: float
    evidence: tuple[str, ...] = ()
    validated_out_of_sample: bool = False

    def __post_init__(self) -> None:
        if self.channel not in CHANNELS:
            raise ValueError("unknown signal channel")
        _utc(self.observed_at)
        if self.horizon_minutes <= 0:
            raise ValueError("invalid forecast horizon")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid confidence")
        if self.expected_tech100_return_pct is not None and not isfinite(self.expected_tech100_return_pct):
            raise ValueError("invalid expected return")


@dataclass(frozen=True)
class SignalContribution:
    channel: str
    expected_pct: float
    effective_weight: float
    weighted_pct: float


@dataclass(frozen=True)
class SynthesisResult:
    at: datetime
    selected: tuple[str, ...]
    status: str
    direction: str
    expected_pct: float | None
    contributions: tuple[SignalContribution, ...]
    unavailable: tuple[str, ...]
    detail: str


def synthesize(
    *,
    at: datetime,
    selected: Sequence[str],
    signals: Sequence[ChannelSignal],
    horizon_minutes: int,
    min_move_pct: float = 0.08,
    max_signal_age: Mapping[str, timedelta] | None = None,
    require_all_selected: bool = True,
) -> SynthesisResult:
    """Explain direction and offset; fail flat if a selected channel is unready.

    ``min_move_pct`` is a *research hypothesis*, not a live trading threshold.
    No channel is double counted, and forecasts for different horizons never mix.
    """
    at = _utc(at)
    chosen = tuple(selected)
    if not chosen or len(set(chosen)) != len(chosen) or any(x not in CHANNELS for x in chosen):
        raise ValueError("select one or more distinct known channels")
    if horizon_minutes <= 0 or not isfinite(min_move_pct) or min_move_pct < 0:
        raise ValueError("invalid horizon or threshold")
    defaults = {
        REGIME: timedelta(minutes=10),
        IMPULSE: timedelta(minutes=2),
        TECH_NEWS: timedelta(minutes=30),
        MACRO_NEWS: timedelta(minutes=30),
    }
    if max_signal_age is not None:
        defaults.update(max_signal_age)
    for value in defaults.values():
        if value < timedelta(0):
            raise ValueError("negative freshness threshold")

    found: dict[str, ChannelSignal] = {}
    for signal in signals:
        if signal.channel in found:
            raise ValueError("duplicate signal channel")
        found[signal.channel] = signal

    unavailable: list[str] = []
    accepted: list[ChannelSignal] = []
    for channel in chosen:
        signal = found.get(channel)
        if (signal is None or signal.expected_tech100_return_pct is None
                or not signal.validated_out_of_sample or signal.confidence <= 0
                or signal.horizon_minutes != horizon_minutes
                or not timedelta(0) <= at - _utc(signal.observed_at) <= defaults[channel]):
            unavailable.append(channel)
        else:
            accepted.append(signal)

    if unavailable and require_all_selected or not accepted:
        return SynthesisResult(at, chosen, "INSUFFICIENT_EVIDENCE", "FLAT", None,
                               (), tuple(unavailable), "Selected signal missing, stale, unvalidated or horizon-mismatched")

    # Weighted mean, not sum: four correlated forecasts must not quadruple risk.
    weight_sum = sum(item.confidence for item in accepted)
    contributions = tuple(SignalContribution(item.channel,
                                              float(item.expected_tech100_return_pct),
                                              item.confidence / weight_sum,
                                              float(item.expected_tech100_return_pct) * item.confidence / weight_sum)
                          for item in accepted)
    estimate = sum(item.weighted_pct for item in contributions)
    direction = "LONG" if estimate > min_move_pct else "SHORT" if estimate < -min_move_pct else "FLAT"
    status = "PAPER_ONLY" if not unavailable else "PAPER_PARTIAL"
    return SynthesisResult(at, chosen, status, direction, estimate,
                           contributions, tuple(unavailable),
                           "Hypothetical research forecast only; no broker execution authority")
