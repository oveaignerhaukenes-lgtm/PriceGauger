"""Read-only causal study: true Impulse Catcher signals -> later regime-price path.

Both one-sided v1.1 models are replayed on the SAME observed Saxo 1s BBO.
All signal features use quotes available by receipt time. Price outcomes begin
at the first fully completed 1m candle after receipt, and require continuous
later 1m candles. Neither outcomes nor hypothetical bid/ask imply LIVE P/L.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_v1 import ImpulseCatcher


HORIZONS_MINUTES = (5, 15, 30, 60)
SEQUENCE_WINDOW_MINUTES = 5
MAX_RESEARCH_QUOTES = 80000  # matches validated source reader's hard cap


def _utc(value) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return stamp.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ImpulsePulse:
    observed_at: datetime
    quote_at: datetime
    direction: str
    trigger_points: float
    threshold_multiple: float
    window_seconds: int
    source_mid: float


@dataclass(frozen=True, slots=True)
class ImpulseRegimeOutcome:
    observed_at: datetime
    direction: str
    horizon_minutes: int
    prior_same_5m: int
    prior_opposite_5m: int
    threshold_multiple: float
    signed_forward_points: float
    signed_forward_pct: float
    max_favorable_points: float
    max_adverse_points: float

    @property
    def sequence(self) -> str:
        if self.prior_opposite_5m:
            return "MOTSTRIDENDE"
        return "1" if self.prior_same_5m == 1 else "2" if self.prior_same_5m == 2 else "3+"

    @property
    def strength(self) -> str:
        return "STERK >=1.5x" if self.threshold_multiple >= 1.5 else "NORMAL <1.5x"


def detect_impulse_pulses_v1(sessions) -> tuple[ImpulsePulse, ...]:
    """Same entry algorithm as v1.1, irrespective of which account is armed.

    Input is validated chronological BboSecond *sessions* from
    tech100_second_impulse_research_v1.prepare_second_quotes. Each session
    starts with a fresh warm-up and never bridges an unobserved quote gap.
    """
    pulses = []
    for session in sessions:
        models = {
            direction: ImpulseCatcher(impulse_catcher_config(direction, "1.1"))
            for direction in ("LONG", "SHORT")
        }
        last_received = None
        for quote in session:
            received = _utc(quote.received)
            at = _utc(quote.at)
            # Quote receipt is the decision clock: never process a quote that
            # would have arrived before an already-consumed later observation.
            if last_received is not None and received < last_received:
                continue
            last_received = received
            for direction, model in models.items():
                decision = model.on_quote(at, quote.bid, quote.ask)
                if decision is None or decision.reason != "QUALIFIED_IMPULSE":
                    continue
                cfg = model.config
                spread = quote.ask - quote.bid
                threshold = max(cfg.min_impulse_points,
                                cfg.relative_impulse_multiple * decision.baseline_points,
                                cfg.spread_impulse_multiple * spread)
                pulses.append(ImpulsePulse(
                    received, at, direction, decision.trigger_points,
                    decision.trigger_points / threshold, decision.window_seconds,
                    decision.price,
                ))
    return tuple(sorted(pulses, key=lambda p: (p.observed_at, p.direction)))


def score_impulse_regime_v1(pulses, bars, *, as_of,
                            horizons=HORIZONS_MINUTES) -> tuple[ImpulseRegimeOutcome, ...]:
    """Score forward *price*, never backfill gaps or use a forming bar.

    Feature window includes the current pulse and earlier *received* pulses.
    The baseline price is the first 1m close observable AFTER that pulse.
    All next H closed candles must exist in the SAME exact instrument series.
    """
    clock = _utc(as_of)
    if any(h not in HORIZONS_MINUTES for h in horizons):
        raise ValueError("Unsupported horizon")
    bar_by_open = {}
    for b in bars:
        stamp = _utc(b.bar_time)
        if stamp in bar_by_open:
            raise ValueError("Duplicate completed bar")
        bar_by_open[stamp] = b
    recent = deque()
    outcomes = []
    previous_at = None
    for pulse in pulses:
        at = _utc(pulse.observed_at)
        if previous_at is not None and at < previous_at:
            raise ValueError("Pulse observations must be chronological")
        previous_at = at
        if at > clock:
            continue
        while recent and recent[0].observed_at < at - timedelta(
                minutes=SEQUENCE_WINDOW_MINUTES):
            recent.popleft()
        recent.append(pulse)
        same = sum(p.direction == pulse.direction for p in recent)
        opposite = len(recent) - same
        # A 12:00:45 signal can only use 12:00's bar after 12:01:00.
        base_open = at.replace(second=0, microsecond=0)
        base = bar_by_open.get(base_open)
        if base is None or base_open + timedelta(minutes=1) > clock:
            continue
        sign = 1 if pulse.direction == "LONG" else -1
        for horizon in horizons:
            end_open = base_open + timedelta(minutes=horizon)
            if end_open + timedelta(minutes=1) > clock:
                continue
            path = [bar_by_open.get(base_open + timedelta(minutes=i))
                    for i in range(1, horizon + 1)]
            if any(b is None for b in path):
                continue
            final_close = float(path[-1].close)
            initial_close = float(base.close)
            if initial_close <= 0:
                continue
            favorable = max(0., *(sign * (float(b.high if sign > 0 else b.low) - initial_close)
                                  for b in path))
            adverse = min(0., *(sign * (float(b.low if sign > 0 else b.high) - initial_close)
                                for b in path))
            change = sign * (final_close - initial_close)
            outcomes.append(ImpulseRegimeOutcome(
                at, pulse.direction, horizon, same, opposite,
                pulse.threshold_multiple, change,
                100 * change / initial_close, favorable, adverse))
    return tuple(outcomes)


def summarize_impulse_regime_v1(outcomes, *, cutoff, min_samples=10):
    """Time-split descriptive groups, excluding training labels past cutoff.

    Events on consecutive minutes are serially dependent. Counts are event
    counts, not independent days/episodes or significance estimates.
    """
    boundary = _utc(cutoff)
    groups = {}
    for item in outcomes:
        at = _utc(item.observed_at)
        # The first outcome price arrives at the first close after the signal;
        # require the entire scoring horizon to mature before train cutoff.
        if at < boundary and at.replace(second=0, microsecond=0) + timedelta(
                minutes=item.horizon_minutes + 1) > boundary:
            continue
        sample = "KALIBRERING" if at < boundary else "HOLDOUT"
        for dimension, value in (("REKKE", item.sequence),
                                 ("STYRKE", item.strength)):
            key = (sample, item.direction, item.horizon_minutes, dimension, value)
            groups.setdefault(key, []).append(item)
    summary = []
    for (sample, direction, horizon, dimension, value), events in sorted(groups.items()):
        summary.append({
            "Del": sample, "Retning": direction, "Minutter": horizon,
            "Måling": dimension, "Kategori": value,
            "Hendelser": len(events),
            "Andel videre %": round(100 * sum(ev.signed_forward_points > 0 for ev in events)
                                       / len(events), 1),
            "Median videre punkter": round(median(ev.signed_forward_points for ev in events), 2),
            "Median maks pluss": round(median(ev.max_favorable_points for ev in events), 2),
            "Median maks minus": round(median(ev.max_adverse_points for ev in events), 2),
            "Nok hendelser": len(events) >= min_samples,
        })
    return tuple(summary)


__all__ = ["HORIZONS_MINUTES", "MAX_RESEARCH_QUOTES", "ImpulsePulse",
           "ImpulseRegimeOutcome", "detect_impulse_pulses_v1",
           "score_impulse_regime_v1", "summarize_impulse_regime_v1"]
