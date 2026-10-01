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
from autotrader_v3_macd_stoch_v1 import (
    STRATEGY_KEY_V3 as STOCH_KEY, MacdStochDecisionV3, macd_stoch_target_v3,
)
from autotrader_v3_macd_trailing_v1 import (
    STRATEGY_KEY_V3 as TRAILING_KEY, MacdTrailingConfigV3,
    MacdTrailingDecisionV3, macd_trailing_target_v3,
)
from database import connect


@dataclass(frozen=True, slots=True)
class ClosedBarDecisionV3:
    decision_key: str
    decision: MacdTrailingDecisionV3 | MacdHistogramDecisionV3 | MacdStochDecisionV3
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


def evaluate_closed_bar_once_v3(*, trader_id: str, observation: MacdObservationV2,
                                strategy_key: str = HISTOGRAM_KEY,
                                config: MacdTrailingConfigV3 | MacdHistogramConfigV3 | None = None,
                                bars: Sequence = (),
                                db_path: str = "pricegauger.db") -> ClosedBarDecisionV3:
    """Persistently reduce one *new* closed MACD bar into one target transition.

    Same/older bars are HOLD and cannot accumulate another tranche after refresh or restart.
    """
    if strategy_key not in {HISTOGRAM_KEY, TRAILING_KEY, STOCH_KEY}:
        raise ValueError(f"unsupported closed-bar V3 strategy: {strategy_key}")
    if config is None:
        config = MacdTrailingConfigV3() if strategy_key in {TRAILING_KEY, STOCH_KEY} else MacdHistogramConfigV3()
    if strategy_key in {TRAILING_KEY, STOCH_KEY} and not isinstance(config, MacdTrailingConfigV3):
        raise TypeError("trailing/MACD-Stoch requires MacdTrailingConfigV3")
    if strategy_key == HISTOGRAM_KEY and not isinstance(config, MacdHistogramConfigV3):
        raise TypeError("histogram requires MacdHistogramConfigV3")
    decide = macd_stoch_target_v3 if strategy_key == STOCH_KEY else (macd_trailing_target_v3 if strategy_key == TRAILING_KEY else macd_histogram_target_v3)
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
                hold=(MacdTrailingDecisionV3 if strategy_key == TRAILING_KEY else (MacdStochDecisionV3 if strategy_key == STOCH_KEY else MacdHistogramDecisionV3))(
                    TargetInventoryV3(target),"HOLD_DUPLICATE",
                    f"closed bar {bar_time} already evaluated",float(observation.spread))
                return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",hold,False)
            previous = None
            if prev_spread is not None:
                previous = MacdObservationV2(bar_time=observation.bar_time, macd=float(prev_spread), signal=0.0)
        else:
            target=0.0; previous=None
        decision=decide(current_target=TargetInventoryV3(target),
            observation=observation,previous_observation=previous,config=config,
            **({"bars": bars} if strategy_key == STOCH_KEY else {}))
        now=datetime.utcnow().isoformat()
        db.execute("""INSERT INTO autotrader_v3_closed_bar_state(trader_id,last_bar_time,target_amount,previous_spread,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(trader_id) DO UPDATE SET last_bar_time=excluded.last_bar_time,
          target_amount=excluded.target_amount,previous_spread=excluded.previous_spread,updated_at=excluded.updated_at""",
          (trader_id,bar_time,decision.target.amount,float(observation.spread),now))
    return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",decision,True)


__all__=["ClosedBarDecisionV3","ensure_closed_bar_driver_schema_v3","evaluate_closed_bar_once_v3"]
