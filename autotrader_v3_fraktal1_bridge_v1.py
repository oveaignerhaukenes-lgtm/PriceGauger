"""Persistent Fraktal#1 -> V3 target bridge; NEVER submits Saxo orders.

Own state is separate for LIVE instance and 'sim:'-prefixed instance.
Broker inventory is adopted on initial activation, external modification,
failed/vetoed target, or context switch. A newly armed strategy can only
enter on a subsequent fully completed 1m candle and fresh confirmed turn.
"""
from __future__ import annotations

from datetime import datetime, timezone

from autotrader_v3_fraktal1_v1 import (
    STRATEGY_KEY_V3, FraktalStateV1, causal_closes_v1, fractal_step_v1,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3, MacdHistogramDecisionV3
from autotrader_v3_closed_bar_driver_v1 import ClosedBarDecisionV3
from database import connect


FRAKTAL1_RUNTIME_KEYS_V3 = frozenset({STRATEGY_KEY_V3})


def ensure_fraktal1_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_fraktal1_state (
          trader_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          last_bar_end TEXT NOT NULL,
          target_amount DOUBLE PRECISION NOT NULL,
          last_open_bar_end TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def clear_fraktal1_state_v3(*, trader_id: str, db_path="pricegauger.db") -> None:
    """Called on V3 strategy/timeframe change or external target alignment."""
    ensure_fraktal1_schema_v3(db_path)
    with connect(db_path) as db:
        db.execute(
            "DELETE FROM autotrader_v3_fraktal1_state WHERE trader_id=?",
            (str(trader_id),),
        )


def evaluate_fraktal1_v3(
    *, trader_id, strategy_key, observation, bars=(), source_bars=(),
    regime_timeframe_minutes=15, market_name="", config=None,
    db_path="pricegauger.db", actual_inventory=None,
    signal_timeframe_minutes=None, now=None,
):
    if strategy_key != STRATEGY_KEY_V3:
        raise ValueError("Unsupported Fraktal#1 strategy key")
    if config is None:
        config=MacdHistogramConfigV3()
    if not isinstance(config, MacdHistogramConfigV3):
        raise TypeError("Fraktal#1 requires Saxo-validated one-unit configuration")
    if signal_timeframe_minutes not in (None, 1):
        raise ValueError("Fraktal#1 v1 only supports 1m closed-signal clock")

    now=now or datetime.now(timezone.utc)
    # A source bar can only enter calculations 10s after completion.
    closes=causal_closes_v1(source_bars,now=now)
    current_broker=TargetInventoryV3(float(actual_inventory or 0.0))
    if closes.empty:
        return ClosedBarDecisionV3(
            f"fraktal:{trader_id}:NO_DATA",
            MacdHistogramDecisionV3(current_broker,"HOLD_NO_DATA",
                                   "Missing valid 1m evidence; no new exposure",0.0),
            False,
        )

    end=closes.index[-1].to_pydatetime()
    context=f"{STRATEGY_KEY_V3}:1m:scales=0.05,0.15,0.35:one-unit"
    ensure_fraktal1_schema_v3(db_path)
    with connect(db_path) as db:
        row=db.execute(
            "SELECT context_key,last_bar_end,target_amount,last_open_bar_end "
            "FROM autotrader_v3_fraktal1_state WHERE trader_id=?",
            (str(trader_id),)
        ).fetchone()

        if row is None or str(row["context_key"])!=context:
            # Never replay a historical pivot as a new live order on startup.
            initial=current_broker.amount
            state=FraktalStateV1(end,initial)
            action="HOLD_BOOTSTRAP"
            reason="Initial activation: adopt actual broker position; wait for next completed bar"
            changed=True
        else:
            prev_end=datetime.fromisoformat(str(row["last_bar_end"]).replace("Z","+00:00"))
            last_open_raw=row["last_open_bar_end"]
            last_open=(
                datetime.fromisoformat(str(last_open_raw).replace("Z","+00:00"))
                if last_open_raw is not None else None
            )
            state=FraktalStateV1(prev_end,float(row["target_amount"]),last_open)
            if end <= prev_end:
                return ClosedBarDecisionV3(
                    f"fraktal:{trader_id}:{state.last_bar_end.isoformat()}",
                    MacdHistogramDecisionV3(
                        TargetInventoryV3(state.target_amount),"HOLD_DUPLICATE",
                        "Already processed canonical 1m bar",0.0,
                    ),False,
                )

            # Do not resurrect expansion vetoed by risk/precheck or overriding
            # Saxo inventory. External position is authoritative, and fresh
            # signal processing resumes only on a *later* candle.
            if (actual_inventory is not None and
                    abs(float(actual_inventory)-state.target_amount)>1e-9):
                state=FraktalStateV1(end,current_broker.amount)
                action="HOLD_BROKER_REALIGN"
                reason="Broker/execution target differs: adopt actual and discard stale entry"
            else:
                decision=fractal_step_v1(state,prices=closes,tranche=config.tranche)
                state=decision.state
                action=decision.action
                reason=decision.reason
            changed=True

        db.execute("""INSERT INTO autotrader_v3_fraktal1_state(
            trader_id,context_key,last_bar_end,target_amount,last_open_bar_end
        ) VALUES(?,?,?,?,?)
        ON CONFLICT(trader_id) DO UPDATE SET
          context_key=excluded.context_key,
          last_bar_end=excluded.last_bar_end,
          target_amount=excluded.target_amount,
          last_open_bar_end=excluded.last_open_bar_end,
          updated_at=CURRENT_TIMESTAMP""",
          (str(trader_id),context,state.last_bar_end.isoformat(),state.target_amount,
           state.last_open_bar_end.isoformat() if state.last_open_bar_end else None))

    result=MacdHistogramDecisionV3(
        TargetInventoryV3(state.target_amount),
        action,
        f"Fraktal#1: {reason}; micro 0.05%, meso 0.15%, macro 0.35%, one legal tranche",
        0.0,
    )
    return ClosedBarDecisionV3(
        f"fraktal:{trader_id}:{state.last_bar_end.isoformat()}",
        result,changed,
    )


__all__=[
    "FRAKTAL1_RUNTIME_KEYS_V3",
    "ensure_fraktal1_schema_v3","clear_fraktal1_state_v3",
    "evaluate_fraktal1_v3",
]
