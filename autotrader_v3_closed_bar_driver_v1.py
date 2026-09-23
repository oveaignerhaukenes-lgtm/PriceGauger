from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3 as MacdTrailingConfigV3, MacdHistogramDecisionV3 as MacdTrailingDecisionV3, macd_histogram_target_v3 as macd_trailing_target_v3
from database import connect


@dataclass(frozen=True, slots=True)
class ClosedBarDecisionV3:
    decision_key: str
    decision: MacdTrailingDecisionV3
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
                                config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
                                db_path: str = "pricegauger.db") -> ClosedBarDecisionV3:
    """Persistently reduce one *new* closed MACD bar into one target transition.

    Same/older bars are HOLD and cannot accumulate another tranche after refresh or restart.
    """
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
                hold=MacdTrailingDecisionV3(TargetInventoryV3(target),"HOLD_DUPLICATE",
                    f"closed bar {bar_time} already evaluated",float(observation.spread))
                return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",hold,False)
            previous = None
            if prev_spread is not None:
                previous = MacdObservationV2(bar_time=observation.bar_time, macd=float(prev_spread), signal=0.0)
        else:
            target=0.0; previous=None
        decision=macd_trailing_target_v3(current_target=TargetInventoryV3(target),
                                         observation=observation,previous_observation=previous,config=config)
        now=datetime.utcnow().isoformat()
        db.execute("""INSERT INTO autotrader_v3_closed_bar_state(trader_id,last_bar_time,target_amount,previous_spread,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(trader_id) DO UPDATE SET last_bar_time=excluded.last_bar_time,
          target_amount=excluded.target_amount,previous_spread=excluded.previous_spread,updated_at=excluded.updated_at""",
          (trader_id,bar_time,decision.target.amount,float(observation.spread),now))
    return ClosedBarDecisionV3(f"{trader_id}|{bar_time}",decision,True)


__all__=["ClosedBarDecisionV3","ensure_closed_bar_driver_schema_v3","evaluate_closed_bar_once_v3"]
