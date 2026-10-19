from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    STRATEGY_KEY_V3 as HISTOGRAM_KEY, MacdHistogramConfigV3,
    MacdHistogramDecisionV3, macd_histogram_target_v3,
)
from autotrader_v3_macd_histogram_flip_build_v1 import (
    STRATEGY_KEY_V3 as HISTOGRAM_FLIP_BUILD_KEY,
    macd_histogram_flip_build_target_v3,
)
from autotrader_v3_macd_histogram_peak_flip_v1 import (
    STRATEGY_KEY_V3 as PEAK_FLIP_KEY,
    HistogramPeakStateV3, histogram_peak_flip_transition_v3,
)
from autotrader_v3_macd_stoch_v1 import (
    STRATEGY_KEY_V3 as STOCH_KEY, MacdStochDecisionV3, macd_stoch_target_v3,
)
from autotrader_v3_macd_stoch_v2 import (
    STRATEGY_KEY_V3 as STOCH_V2_KEY,
    MacdStochV2DecisionV3, macd_stoch_v2_target_v3,
)
from autotrader_v3_macd_stoch_v21 import (
    STRATEGY_KEY_V3 as STOCH_V21_KEY, macd_stoch_v21_target_v3,
)
from autotrader_v3_macd_stoch_rhythm_build_v1 import (
    STRATEGY_KEY_V3 as RHYTHM_BUILD_KEY, macd_stoch_rhythm_build_target_v3,
)
from autotrader_v3_rhythm_trend_v1 import (
    STRATEGY_KEY_V3 as RHYTHM_TREND_KEY, rhythm_trend_target_v3,
)
from autotrader_v3_fractal_rhythm_variants_v1 import (
    RHYTHM_BUILD_FRACTAL_KEY_V3, RHYTHM_TREND_FRACTAL_KEY_V3,
    rhythm_build_fractal_target_v3, rhythm_trend_fractal_target_v3,
)
from autotrader_v3_vwap_regime_histogram_v1 import (
    STRATEGY_KEY_V3 as VWAP_REGIME_KEY,
    vwap_regime_histogram_target_v3,
)
from autotrader_v3_macd_regime_histogram_v1 import (
    STRATEGY_KEY_V3 as MACD_REGIME_HIST_KEY,
    macd_regime_histogram_target_v3,
)
from autotrader_v3_aen2_sticky_regime_v1 import (
    STRATEGY_KEY_V3 as AEN2_STICKY_KEY,
    aen2_sticky_regime_target_v3,
)
from autotrader_v3_aen21_sticky_fast_exit_v1 import (
    STRATEGY_KEY_V3 as AEN21_FAST_EXIT_KEY,
    aen21_sticky_fast_exit_target_v3,
)
from autotrader_v3_macd_flip_v1 import STRATEGY_KEY_V3 as FLIP_KEY, macd_flip_target_v3
from autotrader_v3_macd_trailing_v1 import (
    STRATEGY_KEY_V3 as TRAILING_KEY, MacdTrailingConfigV3,
    MacdTrailingDecisionV3, macd_trailing_target_v3,
)
from database import connect


@dataclass(frozen=True, slots=True)
class ClosedBarDecisionV3:
    decision_key: str
    decision: MacdTrailingDecisionV3 | MacdHistogramDecisionV3 | MacdStochDecisionV3 | MacdStochV2DecisionV3
    is_new: bool


def ensure_closed_bar_driver_schema_v3(db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_closed_bar_state (
          trader_id TEXT PRIMARY KEY,
          last_bar_time TEXT NOT NULL,
          target_amount DOUBLE PRECISION NOT NULL,
          previous_spread DOUBLE PRECISION,
          updated_at TEXT NOT NULL
        )""")
        # Separate, persistent peak/trough memory. Each completed candle
        # advances the normal target and this state in the SAME transaction.
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_aen_core_state (
          trader_id TEXT PRIMARY KEY, context_key TEXT NOT NULL,
          last_bar_end TEXT NOT NULL, target_amount DOUBLE PRECISION NOT NULL,
          signal_minutes INTEGER NOT NULL, arm TEXT NOT NULL,
          active_break INTEGER NOT NULL, protected_level DOUBLE PRECISION,
          cooling_count INTEGER NOT NULL, strength_count INTEGER NOT NULL,
          last_switch TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        # SIM-only Fraktal#1 state is isolated by the 'sim:' trader namespace.
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_fraktal1_state (
          trader_id TEXT PRIMARY KEY, context_key TEXT NOT NULL,
          last_bar_end TEXT NOT NULL, target_amount DOUBLE PRECISION NOT NULL,
          last_open_bar_end TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_histogram_peak_state (
          trader_id TEXT PRIMARY KEY,
          last_bar_time TEXT NOT NULL,
          phase TEXT NOT NULL,
          reference_level DOUBLE PRECISION,
          updated_at TEXT NOT NULL
        )""")


def align_closed_bar_target_v3(*, trader_id: str, target_amount: float,
                               db_path: str = "pricegauger.db") -> bool:
    """Align the persisted strategy target to confirmed broker inventory.

    This preserves the bar cursor and previous histogram observation, so a rejected
    expansion cannot accumulate as an execution backlog while the next fresh bar can
    still make a new one-tranche decision.
    """
    ensure_closed_bar_driver_schema_v3(db_path)
    now = datetime.utcnow().isoformat()
    with connect(db_path) as db:
        original = db.execute(
            "SELECT target_amount FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
            (str(trader_id),),
        ).fetchone()
        cursor = db.execute(
            """UPDATE autotrader_v3_closed_bar_state
               SET target_amount=?,updated_at=? WHERE trader_id=?""",
            (float(target_amount), now, str(trader_id)),
        )
        aen_original=db.execute(
            "SELECT target_amount FROM autotrader_v3_aen_core_state WHERE trader_id=?",
            (str(trader_id),),
        ).fetchone()
        aen_changed=(aen_original is not None and
                     abs(float(aen_original["target_amount"])-float(target_amount))>1e-9)
        if original is not None and (
            abs(float(original["target_amount"]) - float(target_amount)) > 1e-9
        ):
            # An outside guard/reconciliation explicitly changed inventory:
            # discard old reversal extrema rather than reusing stale levels.
            cleared=db.execute("""UPDATE autotrader_v3_histogram_peak_state
                SET phase='WAIT',reference_level=NULL,updated_at=?
                WHERE trader_id=?""",(now,str(trader_id)))
            if cleared.rowcount:
                # This strategy alone must bootstrap afresh after an outside
                # risk/broker alignment: the previously observed slope is NOT
                # permission to reopen the exposure that was just removed.
                db.execute("""UPDATE autotrader_v3_closed_bar_state
                    SET previous_spread=NULL WHERE trader_id=?""",
                    (str(trader_id),))
        if aen_changed:
            # AEn can run without a legacy closed-bar row. Vetoes MUST
            # discard its autonomous target even in that case.
            db.execute("DELETE FROM autotrader_v3_aen_core_state WHERE trader_id=?",
                       (str(trader_id),))
    return cursor.rowcount == 1 or aen_changed


def evaluate_closed_bar_once_v3(*, trader_id: str, observation: MacdObservationV2,
                                strategy_key: str = HISTOGRAM_KEY,
                                config: MacdTrailingConfigV3 | MacdHistogramConfigV3 | None = None,
                                bars: Sequence = (), source_bars: Sequence = (),
                                regime_timeframe_minutes: int = 15, market_name: str = "",
                                db_path: str = "pricegauger.db") -> ClosedBarDecisionV3:
    """Persistently reduce one *new* closed MACD bar into one target transition.

    Same/older bars are HOLD and cannot accumulate another tranche after refresh or restart.
    """
    if strategy_key not in {HISTOGRAM_KEY, HISTOGRAM_FLIP_BUILD_KEY, PEAK_FLIP_KEY, VWAP_REGIME_KEY, MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY, TRAILING_KEY, FLIP_KEY, STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY, RHYTHM_BUILD_KEY, RHYTHM_TREND_KEY, RHYTHM_BUILD_FRACTAL_KEY_V3, RHYTHM_TREND_FRACTAL_KEY_V3}:
        raise ValueError(f"unsupported closed-bar V3 strategy: {strategy_key}")
    if config is None:
        config = MacdTrailingConfigV3() if strategy_key in {TRAILING_KEY, FLIP_KEY, STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY, RHYTHM_BUILD_KEY, RHYTHM_BUILD_FRACTAL_KEY_V3} else MacdHistogramConfigV3()
    if strategy_key in {TRAILING_KEY, FLIP_KEY, STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY, RHYTHM_BUILD_KEY, RHYTHM_BUILD_FRACTAL_KEY_V3} and not isinstance(config, MacdTrailingConfigV3):
        raise TypeError("trailing/MACD-Stoch requires MacdTrailingConfigV3")
    if strategy_key in {HISTOGRAM_KEY, HISTOGRAM_FLIP_BUILD_KEY, PEAK_FLIP_KEY, VWAP_REGIME_KEY, MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY, RHYTHM_TREND_KEY, RHYTHM_TREND_FRACTAL_KEY_V3} and not isinstance(config, MacdHistogramConfigV3):
        raise TypeError("histogram strategies require MacdHistogramConfigV3")
    if strategy_key == RHYTHM_BUILD_KEY:
        decide = macd_stoch_rhythm_build_target_v3
    elif strategy_key == RHYTHM_TREND_KEY:
        decide = rhythm_trend_target_v3
    elif strategy_key == RHYTHM_BUILD_FRACTAL_KEY_V3:
        decide = rhythm_build_fractal_target_v3
    elif strategy_key == RHYTHM_TREND_FRACTAL_KEY_V3:
        decide = rhythm_trend_fractal_target_v3
    elif strategy_key == STOCH_V21_KEY:
        decide = macd_stoch_v21_target_v3
    elif strategy_key == STOCH_V2_KEY:
        decide = macd_stoch_v2_target_v3
    elif strategy_key == STOCH_KEY:
        decide = macd_stoch_target_v3
    elif strategy_key == TRAILING_KEY:
        decide = macd_trailing_target_v3
    elif strategy_key == FLIP_KEY:
        decide = macd_flip_target_v3
    elif strategy_key == HISTOGRAM_FLIP_BUILD_KEY:
        decide = macd_histogram_flip_build_target_v3
    elif strategy_key == PEAK_FLIP_KEY:
        decide = histogram_peak_flip_transition_v3
    elif strategy_key == VWAP_REGIME_KEY:
        decide = vwap_regime_histogram_target_v3
    elif strategy_key == MACD_REGIME_HIST_KEY:
        decide = macd_regime_histogram_target_v3
    elif strategy_key == AEN2_STICKY_KEY:
        decide = aen2_sticky_regime_target_v3
    elif strategy_key == AEN21_FAST_EXIT_KEY:
        decide = aen21_sticky_fast_exit_target_v3
    else:
        decide = macd_histogram_target_v3
    ensure_closed_bar_driver_schema_v3(db_path)
    bar_time = observation.bar_time.isoformat()
    with connect(db_path) as db:
        row = db.execute("SELECT last_bar_time,target_amount,previous_spread FROM autotrader_v3_closed_bar_state WHERE trader_id=?",
                         (trader_id,)).fetchone()
        if row is not None:
            last = str(row["last_bar_time"] if isinstance(row,dict) else row[0])
            target = float(row["target_amount"] if isinstance(row,dict) else row[1])
            prev_spread = row["previous_spread"] if isinstance(row,dict) else row[2]
            if bar_time <= last:
                hold_type=(
                    MacdTrailingDecisionV3 if strategy_key in {TRAILING_KEY, FLIP_KEY}
                    else MacdStochDecisionV3 if strategy_key == STOCH_KEY
                    else MacdStochV2DecisionV3 if strategy_key in {STOCH_V2_KEY, STOCH_V21_KEY, RHYTHM_BUILD_KEY, RHYTHM_BUILD_FRACTAL_KEY_V3}
                    else MacdHistogramDecisionV3
                )
                hold=hold_type(
                    TargetInventoryV3(target),"HOLD_DUPLICATE",
                    f"closed bar {bar_time} already evaluated",float(observation.spread))
                return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",hold,False)
            previous = None
            if prev_spread is not None:
                previous = MacdObservationV2(bar_time=observation.bar_time, macd=float(prev_spread), signal=0.0)
        else:
            target=0.0; previous=None
        extra = {}
        if strategy_key in {STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY, RHYTHM_BUILD_KEY, RHYTHM_BUILD_FRACTAL_KEY_V3}:
            extra["bars"] = bars
            if strategy_key == RHYTHM_BUILD_FRACTAL_KEY_V3:
                extra["source_bars"] = source_bars
        elif strategy_key == VWAP_REGIME_KEY:
            extra["source_bars"] = source_bars
        elif strategy_key in {MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY, RHYTHM_TREND_KEY, RHYTHM_TREND_FRACTAL_KEY_V3}:
            extra["source_bars"] = source_bars
            extra["regime_timeframe_minutes"] = int(regime_timeframe_minutes)
            extra["market_name"] = str(market_name)
            if strategy_key in {RHYTHM_TREND_KEY, RHYTHM_TREND_FRACTAL_KEY_V3}:
                # Macro/meso consume raw canonical source; M1 rhythm additionally
                # needs the fully closed 1m OHLC decision bars, not the default ().
                extra["bars"] = bars
        if strategy_key == PEAK_FLIP_KEY:
            memory_row=db.execute(
                """SELECT last_bar_time,phase,reference_level
                   FROM autotrader_v3_histogram_peak_state WHERE trader_id=?""",
                (trader_id,),
            ).fetchone()
            # Never carry a peak across a change of strategy, a foreign
            # closed-bar cursor or a reset of the previous MACD observation.
            memory_valid=(
                memory_row is not None and row is not None and previous is not None
                and str(memory_row["last_bar_time"]) == last
            )
            memory = (HistogramPeakStateV3(
                str(memory_row["phase"]),
                None if memory_row["reference_level"] is None
                else float(memory_row["reference_level"]),
            ) if memory_valid else HistogramPeakStateV3())
            if not memory_valid:
                previous = None
            peak_transition=decide(
                current_target=TargetInventoryV3(target),
                observation=observation,previous_observation=previous,
                state=memory,config=config,
            )
            decision=peak_transition.decision
        else:
            decision=decide(current_target=TargetInventoryV3(target),
                observation=observation,previous_observation=previous,config=config,**extra)
        now=datetime.utcnow().isoformat()
        db.execute("""INSERT INTO autotrader_v3_closed_bar_state(trader_id,last_bar_time,target_amount,previous_spread,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(trader_id) DO UPDATE SET last_bar_time=excluded.last_bar_time,
          target_amount=excluded.target_amount,previous_spread=excluded.previous_spread,updated_at=excluded.updated_at""",
          (trader_id,bar_time,decision.target.amount,float(observation.spread),now))
        if strategy_key == PEAK_FLIP_KEY:
            db.execute("""INSERT INTO autotrader_v3_histogram_peak_state(
                trader_id,last_bar_time,phase,reference_level,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(trader_id) DO UPDATE SET
                    last_bar_time=excluded.last_bar_time,
                    phase=excluded.phase,
                    reference_level=excluded.reference_level,
                    updated_at=excluded.updated_at""",
                (trader_id,bar_time,peak_transition.state.phase,
                 peak_transition.state.reference,now))
    return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",decision,True)


__all__=["ClosedBarDecisionV3","align_closed_bar_target_v3","ensure_closed_bar_driver_schema_v3","evaluate_closed_bar_once_v3"]
