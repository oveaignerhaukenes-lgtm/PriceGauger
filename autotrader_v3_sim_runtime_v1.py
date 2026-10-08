from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_v3_closed_bar_driver_v1 import ensure_closed_bar_driver_schema_v3
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_registry_v1 import fixed_timeframe_minutes_v3, sim_config_issues_v3
from autotrader_v3_macd_regime_histogram_v1 import STRATEGY_KEY_V3 as MACD_REGIME_HIST_KEY
from autotrader_v3_aen2_sticky_regime_v1 import STRATEGY_KEY_V3 as AEN2_STICKY_KEY
from autotrader_v3_aen21_sticky_fast_exit_v1 import STRATEGY_KEY_V3 as AEN21_FAST_EXIT_KEY
from autotrader_v3_runtime_instances_v1 import load_v3_runtime_instances_v1
from autotrader_v3_sim_authority_v1 import sim_authority_armed_v3
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect

LOGGER = logging.getLogger("pricegauger.autotrader.v3.sim")
REGIME_RUNTIME_KEYS_V3 = {MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY}


def _sim_state_id_v3(instance_id: str) -> str:
    """Keep SIM closed-bar state physically separate from the same instance's LIVE state."""
    return f"sim:{str(instance_id)}"


def _record_sim_runtime_v3(trader_id: str, status: str, detail: str = "", *, db_path: str) -> None:
    LOGGER.info("v3 SIM runtime trader=%s status=%s detail=%s", trader_id, status, detail)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_sim_runtime_state(
          trader_id TEXT PRIMARY KEY,status TEXT NOT NULL,detail TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""INSERT INTO autotrader_v3_sim_runtime_state(trader_id,status,detail,updated_at)
          VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(trader_id) DO UPDATE SET
          status=excluded.status,detail=excluded.detail,updated_at=CURRENT_TIMESTAMP""",
          (str(trader_id), str(status), str(detail)))


def _prepare_sim_decision_context_v3(*, instance_id: str, strategy_key: str,
                                     timeframe_minutes: int, db_path: str) -> bool:
    """Reset cross-bar impulse memory when SIM strategy/timeframe changes."""
    ensure_closed_bar_driver_schema_v3(db_path)
    state_id = _sim_state_id_v3(instance_id)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_sim_decision_context(
          trader_id TEXT PRIMARY KEY,strategy_key TEXT NOT NULL,
          timeframe_minutes INTEGER NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        row = db.execute(
            "SELECT strategy_key,timeframe_minutes FROM autotrader_v3_sim_decision_context WHERE trader_id=?",
            (str(instance_id),),
        ).fetchone()
        if row is None:
            changed = False
        else:
            get = lambda key, idx: row[key] if isinstance(row, dict) else row[idx]
            changed = (
                str(get("strategy_key", 0)) != str(strategy_key)
                or int(get("timeframe_minutes", 1)) != int(timeframe_minutes)
            )
        if changed:
            db.execute(
                "UPDATE autotrader_v3_closed_bar_state SET previous_spread=NULL WHERE trader_id=?",
                (state_id,),
            )
        db.execute("""INSERT INTO autotrader_v3_sim_decision_context(
          trader_id,strategy_key,timeframe_minutes,updated_at)
          VALUES(?,?,?,CURRENT_TIMESTAMP)
          ON CONFLICT(trader_id) DO UPDATE SET
            strategy_key=excluded.strategy_key,
            timeframe_minutes=excluded.timeframe_minutes,
            updated_at=CURRENT_TIMESTAMP""",
          (str(instance_id), str(strategy_key), int(timeframe_minutes)))
    return changed


def run_v3_sim_cycle_v1(*, db_path: str = "pricegauger.db", now=None) -> int:
    """Evaluate canonical armed V3 SIM instances with their configured strategy/timeframe.

    SIM has no broker mutation authority. Unsupported SIM settings fail closed and are
    surfaced in the SIM runtime state instead of being silently ignored.
    """
    processed = 0
    end = now or datetime.now(timezone.utc)

    for instance in load_v3_runtime_instances_v1(db_path=db_path):
        if not sim_authority_armed_v3(instance.pilot_key, db_path=db_path):
            continue

        config = load_autotrader_config_v3(instance.pilot_key, db_path=db_path)
        issues = sim_config_issues_v3(
            strategy_key=config.strategy_key,
            timeframe=config.timeframe,
            control_mode=config.control_mode,
            modifiers=config.modifiers,
            regime_timeframe=config.regime_timeframe,
        )
        if issues:
            _record_sim_runtime_v3(
                instance.pilot_key,
                "BLOCKED",
                "V3 SIM config unsupported: " + "; ".join(issues),
                db_path=db_path,
            )
            continue

        adapter = STRATEGIES_V3.get(instance.strategy_key)
        if adapter is None:
            _record_sim_runtime_v3(
                instance.pilot_key,
                "BLOCKED",
                f"Unregistered V3 SIM runtime strategy {instance.strategy_key}",
                db_path=db_path,
            )
            continue

        timeframe_minutes = fixed_timeframe_minutes_v3(config.timeframe)
        regime_timeframe_minutes = fixed_timeframe_minutes_v3(config.regime_timeframe)
        context_strategy_key = (
            f"{instance.strategy_key}:R{config.regime_timeframe}"
            if instance.strategy_key in REGIME_RUNTIME_KEYS_V3 else instance.strategy_key
        )
        context_changed = _prepare_sim_decision_context_v3(
            instance_id=instance.pilot_key,
            strategy_key=context_strategy_key,
            timeframe_minutes=timeframe_minutes,
            db_path=db_path,
        )
        if context_changed:
            LOGGER.info(
                "v3 SIM decision context changed trader=%s strategy=%s timeframe=%s regime=%s",
                instance.pilot_key, instance.strategy_key, config.timeframe, config.regime_timeframe,
            )

        bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=instance.instrument_id,
            start=end - timedelta(days=14),
            end=end,
            limit=20000,
        )
        if not bars:
            _record_sim_runtime_v3(instance.pilot_key, "DEGRADED", "no canonical bars", db_path=db_path)
            continue

        closed = closed_bars_v2(
            tuple(item.point for item in bars),
            market=instance.market_name,
            timeframe_minutes=timeframe_minutes,
        )
        observations = macd_observations_v2(closed, timeframe_minutes=timeframe_minutes)
        if not observations:
            _record_sim_runtime_v3(
                instance.pilot_key,
                "DEGRADED",
                f"no closed {config.timeframe} MACD observation",
                db_path=db_path,
            )
            continue

        result = evaluate_strategy_bar_v3(
            trader_id=_sim_state_id_v3(instance.pilot_key),
            observation=observations[-1],
            strategy_key=instance.strategy_key,
            bars=closed,
            source_bars=tuple(bars),
            regime_timeframe_minutes=regime_timeframe_minutes,
            market_name=instance.market_name,
            db_path=db_path,
        )
        processed += int(result.is_new)
        _record_sim_runtime_v3(
            instance.pilot_key,
            "RUNNING",
            f"strategy={config.strategy_key} runtime={instance.strategy_key} "
            f"timeframe={config.timeframe} "
            + (f"regime={config.regime_timeframe} " if instance.strategy_key in REGIME_RUNTIME_KEYS_V3 else "")
            + f"new_bar={bool(result.is_new)}",
            db_path=db_path,
        )
    return processed


def run_v3_macd_trailing_sim_cycle_v1(*, db_path: str = "pricegauger.db", now=None) -> int:
    """Compatibility alias for the old worker import."""
    return run_v3_sim_cycle_v1(db_path=db_path, now=now)


__all__ = [
    "run_v3_sim_cycle_v1",
    "run_v3_macd_trailing_sim_cycle_v1",
]
