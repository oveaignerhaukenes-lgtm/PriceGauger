"""PAPER-only R15 exit hypotheses for the existing Impulse Catcher v1.3.

R15 uses exactly one UIC's stored, fully completed and contiguous Saxo 1m
bars. A 15m MACD observation is eligible only *after* its candle closes;
there is no forward filling across missing bars or market closures.

This module does not register any LIVE strategy, talk to Saxo, or write to PG.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from autotrader_impulse_catcher_profiles_v1 import impulse_catcher_config
from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig
from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _utc


PAPER_EXIT_MODES = (
    "v1.3",
    "begge_venter_5s",
    "r15_short_bear_venter_5s",
    "r15_medvind_venter_motvind_rask",
)

STRUCTURE_EXIT_MODES = (
    "v1.3",
    "struktur_motvind_rask",
    "struktur_medvind_venter_motvind_rask",
)


@dataclass(frozen=True, slots=True)
class R15RegimeTimelinePaper:
    closed_at: tuple[datetime, ...]
    states: tuple[str, ...]

    def state_asof(self, at: datetime) -> str:
        stamp = _utc(at)
        idx = bisect_right(self.closed_at, stamp) - 1
        if idx < 0 or stamp - self.closed_at[idx] >= timedelta(minutes=15):
            return "UKJENT"
        return self.states[idx]


def r15_timeline_from_closed_1m_paper(*, source_bars, cutoff,
                                      market_name: str) -> R15RegimeTimelinePaper:
    """MACD sign after 35 strictly consecutive closed 15m candles.

    Reinitializing at every data gap prevents an old EMA from silently
    carrying over overnight/weekends. No candle after cutoff is considered.
    """
    combined = _completed_bars(source_bars, timeframe=15,
                               cutoff=cutoff, market=market_name)
    segments = []
    current = []
    for bar in combined:
        if current and _utc(bar.bar_time) != _utc(current[-1].bar_time) + timedelta(minutes=15):
            segments.append(tuple(current))
            current = []
        current.append(bar)
    if current:
        segments.append(tuple(current))
    stamps, states = [], []
    for segment in segments:
        if len(segment) < 35:
            continue
        observations = macd_observations_v2(segment, timeframe_minutes=15)
        first_allowed = _utc(segment[34].bar_time) + timedelta(minutes=15)
        for observation in observations:
            if _utc(observation.closed_at) < first_allowed:
                continue
            stamps.append(_utc(observation.closed_at))
            if observation.spread < 0:
                states.append("BEAR")
            elif observation.spread > 0:
                states.append("BULL")
            else:
                states.append("UKJENT")
    return R15RegimeTimelinePaper(tuple(stamps), tuple(states))


def paper_exit_config_for_quote(*, side: str, mode: str,
                                r15_state: str) -> ImpulseCatcherConfig:
    """Keep v1.3 entries, quote-gap and urgent reversal exactly unchanged."""
    if mode not in PAPER_EXIT_MODES:
        raise ValueError("Unknown PAPER exit mode")
    cfg = impulse_catcher_config(side, "1.3")
    if mode == "v1.3":
        return cfg
    if mode == "begge_venter_5s":
        return replace(cfg, exhaustion_seconds=11.)
    if mode == "r15_short_bear_venter_5s":
        return (replace(cfg, exhaustion_seconds=11.)
                if side == "SHORT" and r15_state == "BEAR" else cfg)
    aligned = ((side == "SHORT" and r15_state == "BEAR") or
               (side == "LONG" and r15_state == "BULL"))
    opposed = ((side == "SHORT" and r15_state == "BULL") or
               (side == "LONG" and r15_state == "BEAR"))
    if aligned:
        return replace(cfg, exhaustion_seconds=11.)
    if opposed:
        return replace(cfg, exhaustion_seconds=3.)
    return cfg


def paper_structure_exit_config_for_quote(*, side: str, mode: str,
                                          structure_state: str) -> ImpulseCatcherConfig:
    """Price structure, not MACD: fast normal exit against clear multi-hour trend.

    Countertrend impulses are still entered with unchanged v1.3 triggers.
    Urgent retrace and stale BBO safeguards always take precedence.
    """
    if mode not in STRUCTURE_EXIT_MODES:
        raise ValueError("Unknown PAPER structure exit mode")
    cfg = impulse_catcher_config(side, "1.3")
    if mode == "v1.3" or structure_state not in ("BEAR", "BULL"):
        return cfg
    opposed = ((side == "LONG" and structure_state == "BEAR") or
               (side == "SHORT" and structure_state == "BULL"))
    aligned = ((side == "LONG" and structure_state == "BULL") or
               (side == "SHORT" and structure_state == "BEAR"))
    if opposed:
        return replace(cfg, exhaustion_seconds=3.)
    if aligned and mode == "struktur_medvind_venter_motvind_rask":
        return replace(cfg, exhaustion_seconds=11.)
    return cfg

