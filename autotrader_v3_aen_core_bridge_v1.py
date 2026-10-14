"""AEn Core -> V3 incremental target adapter (LIVE-capable, never order-capable).

Exactly the five frozen one-unit AEn research families are exposed:
MACD Hold, MACD Histogram, MACD Hysteresis, MACD + Stochastic and deterministic
Adaptive Hold. The bridge consumes completed, canonical 1m bars and persists
its OWN structure/auto state; historical paper fills are NEVER converted to
LIVE orders. V3's ordinary ownership, capacity, cost and flat-first execution
layer alone owns all broker mutations.

AEn advanced modules (scaling beyond one unit, impulse, confirmation ladder,
AI timeframes) are deliberately not represented as LIVE-equivalent yet.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from aen_core_v1 import StructureEvent
from aen_replay_v1 import (
    AEnPaperConfig, Indicator, TIMEFRAMES, _desired_regime, _propose,
    prepare_replay_inputs, utc,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramDecisionV3
from database import connect

AEN_CORE_PRESETS_V3 = {
    "aen-core-hold-v1": ("MACD Hold", False),
    "aen-core-histogram-v1": ("MACD Histogram", False),
    "aen-core-hysteresis-v1": ("MACD Hysteresis", False),
    "aen-core-stoch-v1": ("MACD + Stochastic", False),
    "aen-core-auto-v1": ("MACD Hold", True),
}
AEN_CORE_KEYS_V3 = frozenset(AEN_CORE_PRESETS_V3)
STRUCTURE_MINUTES_V3 = 5
MIN_FRESH_SECONDS_V3 = 10
MAX_HISTORY_BARS_V3 = 3000


@dataclass(frozen=True, slots=True)
class AEnV3State:
    last_bar_end: str
    target_amount: float
    signal_minutes: int
    arm: str = "HOLD"
    active_break: bool = False
    protected_level: float | None = None
    cooling_count: int = 0
    strength_count: int = 0
    last_switch: str | None = None

    def __post_init__(self):
        if self.signal_minutes not in TIMEFRAMES or self.arm not in {"HOLD", "LONG", "SHORT"}:
            raise ValueError("invalid AEn V3 state")
        if not isfinite(self.target_amount):
            raise ValueError("invalid AEn target")


@dataclass(frozen=True, slots=True)
class AEnStepV3:
    state: AEnV3State
    reason: str


def aen_core_step_v3(*, state: AEnV3State, config: AEnPaperConfig,
                     at: datetime, indicator_sets: dict,
                     events: Sequence[StructureEvent],
                     tranche: float, bar_close: float | None = None) -> AEnStepV3:
    """Exactly ONE freshly completed 1m candle; pure, no fills or DB.

    Missing 1m bars reset provisional structure and SUPPRESS retroactive signals.
    MACD and confirmed swing pivots use the identical AEn research primitives.
    """
    end = utc(at)
    previous = utc(state.last_bar_end)
    if end <= previous:
        return AEnStepV3(state, "HOLD_DUPLICATE")
    if end - previous != timedelta(minutes=1):
        return AEnStepV3(replace(state,last_bar_end=end,arm="HOLD",
                                 active_break=False,cooling_count=0,
                                 strength_count=0), "HOLD_MISSING_1M")
    minute = state.signal_minutes
    obs = max(
        (indicator for t,indicator in indicator_sets.get(minute,{}).items() if t<=end),
        default=None,key=lambda o:o.end,
    )
    fresh = obs is not None and obs.end == end
    cooling = state.cooling_count
    strengthening = state.strength_count
    if config.adaptive and fresh:
        losing = obs.histogram*(obs.histogram - obs.previous_histogram)<0
        gaining = obs.histogram*(obs.histogram - obs.previous_histogram)>0
        cooling = cooling+1 if losing else 0
        strengthening = strengthening+1 if gaining else 0
        proposal = _propose(minute,obs,cooling_count=cooling,strength_count=strengthening)
        previous_switch = utc(state.last_switch) if state.last_switch else None
        if proposal!=minute and (previous_switch is None or
                                 end-previous_switch>=timedelta(minutes=config.dwell_minutes)):
            return AEnStepV3(replace(
                state,last_bar_end=end,signal_minutes=proposal,
                cooling_count=0,strength_count=0,last_switch=end.isoformat(),
            ), f"AUTO_TIMEFRAME_{minute}m_TO_{proposal}m_NO_TRADE")

    desired = _desired_regime(config,obs) if obs else "HOLD"
    if obs is None or end-obs.end>timedelta(minutes=max(2,minute*2)):
        desired = "HOLD"
    target=state.target_amount
    side="LONG" if target>0 else "SHORT" if target<0 else "HOLD"
    arm=state.arm
    broken=state.active_break
    protected=state.protected_level
    reason="HOLD"
    # All exits go to FLAT. The V3 executor, not this signal engine, owns
    # CLOSE -> broker-confirmed FLAT -> OPEN for any subsequent opposite entry.
    for ev in events:
        if ev.kind=="HH":
            arm="LONG"
            if side=="SHORT":
                broken=True
        elif ev.kind=="LL":
            arm="SHORT"
            if side=="LONG":
                broken=True
        if side=="LONG" and broken and ev.kind=="LH":
            target=0.0
            reason="STRUCTURE_LH_FLAT"
            break
        if side=="SHORT" and broken and ev.kind=="HL":
            target=0.0
            reason="STRUCTURE_HL_FLAT"
            break
        if ev.kind=="HL" and arm=="LONG" and desired=="LONG":
            if side=="HOLD":
                target=tranche
                reason="HH_HL_OPEN"
                protected=ev.level
                broken=False
                break
            if side=="LONG" and not broken:
                protected=ev.level
        if ev.kind=="LH" and arm=="SHORT" and desired=="SHORT":
            if side=="HOLD":
                target=-tranche
                reason="LL_LH_OPEN"
                protected=ev.level
                broken=False
                break
            if side=="SHORT" and not broken:
                protected=ev.level

    if reason=="HOLD" and side!="HOLD" and protected is not None and bar_close is not None:
        price=float(bar_close)
        if not isfinite(price) or price<=0:
            raise ValueError("invalid completed-bar close")
        breach=(price<protected if side=="LONG" else price>protected)
        if breach:
            target=0.0
            reason="PROTECTED_SWING_FLAT"
    if reason=="HOLD" and side!="HOLD" and fresh and desired in ("LONG","SHORT"):
        if desired!=side:
            target=0.0
            reason="MACD_REVERSE_FLAT"
    if abs(target)>abs(tranche)+1e-9 and abs(target-state.target_amount)>1e-9:
        raise ValueError("AEn V3 one-tranche cap exceeded")
    if target==0:
        protected=None
        broken=False
    return AEnStepV3(AEnV3State(
        last_bar_end=end.isoformat(),target_amount=target,signal_minutes=minute,
        arm=arm,active_break=broken,protected_level=protected,
        cooling_count=cooling,strength_count=strengthening,
        last_switch=state.last_switch,
    ),reason)


def ensure_aen_v3_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_aen_core_state (
          trader_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          last_bar_end TEXT NOT NULL,
          target_amount DOUBLE PRECISION NOT NULL,
          signal_minutes INTEGER NOT NULL,
          arm TEXT NOT NULL,
          active_break INTEGER NOT NULL,
          protected_level DOUBLE PRECISION,
          cooling_count INTEGER NOT NULL,
          strength_count INTEGER NOT NULL,
          last_switch TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def evaluate_aen_core_v3(*, trader_id, strategy_key, observation, bars=(),
                         source_bars=(), regime_timeframe_minutes=15,
                         market_name="", config=None, db_path="pricegauger.db",
                         actual_inventory=None, signal_timeframe_minutes=None,
                         now=None):
    """V3 adapter: atomic closed-1m cursor, NOT a historical replay portfolio.

    The current signal is eligible only after the latest 1m close, and never
    more than one fresh minute after the preceding cursor. Startup and context
    changes bootstrap HOLD; older simulated entries cannot become new LIVE.
    """
    from autotrader_v3_closed_bar_driver_v1 import ClosedBarDecisionV3
    from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3

    if strategy_key not in AEN_CORE_KEYS_V3:
        raise ValueError("unknown AEn Core strategy")
    if config is None:
        config=MacdHistogramConfigV3()
    if not isinstance(config,MacdHistogramConfigV3):
        raise TypeError("AEn LIVE requires Saxo-validated histogram tranche")
    minutes=int(signal_timeframe_minutes or
                getattr(observation,"timeframe_minutes",5))
    if minutes not in TIMEFRAMES:
        raise ValueError("unsupported AEn resolution")
    family,adaptive=AEN_CORE_PRESETS_V3[strategy_key]
    cfg=AEnPaperConfig(family=family,minutes=minutes,
         structure_minutes=STRUCTURE_MINUTES_V3,max_units=1,adaptive=adaptive,
         structure_scaling=False,confirmation_ladder=False,
         impulse_enabled=False)
    moment=utc(now or datetime.now(timezone.utc))
    source=[b for b in source_bars
            if utc(b.bar_time)+timedelta(minutes=1,seconds=MIN_FRESH_SECONDS_V3)<=moment]
    source=sorted(source,key=lambda b:utc(b.bar_time))[-MAX_HISTORY_BARS_V3:]
    if not source:
        d=MacdHistogramDecisionV3(TargetInventoryV3(
            float(actual_inventory or 0)),"HOLD_NO_DATA",
            "No finished canonical 1m bars; no LIVE target",0.0)
        return ClosedBarDecisionV3(f"aen:{trader_id}:NO_DATA",d,False)
    prepared=prepare_replay_inputs(source,cfg)
    if not prepared.minute_bars:
        d=MacdHistogramDecisionV3(TargetInventoryV3(
            float(actual_inventory or 0)),"HOLD_NO_DATA",
            "No fully contiguous canonical 1m bar",0.0)
        return ClosedBarDecisionV3(f"aen:{trader_id}:NO_DATA",d,False)
    end=prepared.minute_bars[-1].end
    context=f"{strategy_key}:S{minutes}:structure{STRUCTURE_MINUTES_V3}:one-unit"
    ensure_aen_v3_schema(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT * FROM autotrader_v3_aen_core_state
            WHERE trader_id=?""",(str(trader_id),)).fetchone()
        if row is not None and str(row["context_key"])==context:
            state=AEnV3State(
                str(row["last_bar_end"]),float(row["target_amount"]),
                int(row["signal_minutes"]),str(row["arm"]),
                bool(row["active_break"]),
                None if row["protected_level"] is None else float(row["protected_level"]),
                int(row["cooling_count"]),int(row["strength_count"]),
                row["last_switch"],
            )
            if end<=utc(state.last_bar_end):
                decision=MacdHistogramDecisionV3(
                    TargetInventoryV3(state.target_amount),"HOLD_DUPLICATE",
                    "AEn already processed this completed 1m bar",
                    0.0)
                return ClosedBarDecisionV3(f"aen:{trader_id}:{state.last_bar_end}",
                                           decision,False)
            events=prepared.structure_events.get(end,())
            step=aen_core_step_v3(
                state=state,config=cfg,at=end,
                indicator_sets=prepared.indicators,events=events,
                tranche=config.tranche,bar_close=prepared.minute_bars[-1].close,
            )
            action=step.reason
            updated=step.state
        else:
            # First strategy activation/context switch: preserve ACTUAL Saxo
            # inventory and await a new completed bar, never copy old SIM fills.
            starting=float(actual_inventory) if actual_inventory is not None else 0.0
            updated=AEnV3State(end.isoformat(),starting,minutes)
            action="HOLD_BOOTSTRAP"
        db.execute("""INSERT INTO autotrader_v3_aen_core_state(
            trader_id,context_key,last_bar_end,target_amount,signal_minutes,
            arm,active_break,protected_level,cooling_count,strength_count,last_switch)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trader_id) DO UPDATE SET
            context_key=excluded.context_key,last_bar_end=excluded.last_bar_end,
            target_amount=excluded.target_amount,signal_minutes=excluded.signal_minutes,
            arm=excluded.arm,active_break=excluded.active_break,
            protected_level=excluded.protected_level,
            cooling_count=excluded.cooling_count,
            strength_count=excluded.strength_count,
            last_switch=excluded.last_switch,updated_at=CURRENT_TIMESTAMP""",
            (str(trader_id),context,updated.last_bar_end,updated.target_amount,
             updated.signal_minutes,updated.arm,int(updated.active_break),
             updated.protected_level,updated.cooling_count,
             updated.strength_count,updated.last_switch))
    decision=MacdHistogramDecisionV3(
        TargetInventoryV3(updated.target_amount),action,
        f"AEn Core {family} {updated.signal_minutes}m/structure 5m: {action}; "
        "one tranche; no historical fill mirroring",
        0.0)
    return ClosedBarDecisionV3(
        f"aen:{trader_id}:{updated.last_bar_end}",decision,True)


__all__=["AEN_CORE_PRESETS_V3","AEN_CORE_KEYS_V3",
         "aen_core_step_v3","evaluate_aen_core_v3","ensure_aen_v3_schema"]
