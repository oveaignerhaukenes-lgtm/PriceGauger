from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

from autotrader_aen1_series_v1 import SERIES_VERSION as AEN1_SERIES_VERSION, load_aen1_series_v1
from autotrader_aen1_v1 import STRATEGY_KEY as AEN1_STRATEGY_KEY
from autotrader_ai_baseline_fresh_series_v1 import FRESH_SERIES_VERSION_V1 as AI_BASELINE_FRESH_SERIES_VERSION, load_ai_baseline_fresh_series_v1
from autotrader_cocktail_mode_1_shadow_v2 import CONFIG_VERSION as COCKTAIL_CONFIG_VERSION
from autotrader_macd_a_series_v1 import MACD_A_SERIES_VERSION_V1, load_macd_a_series_v1
from autotrader_macd_hybrid_v1 import HYBRID_SERIES_VERSION_V1, HYBRID_STRATEGY_KEYS_V1, load_macd_hybrid_series_v1
from autotrader_macd_timeframe_controls_v1 import MACD_CONTROL_STRATEGY_KEYS_V1, SERIES_VERSION_V1 as MACD_TIMEFRAME_SERIES_VERSION, load_macd_timeframe_control_series_v1
from autotrader_overseer_performance_series_v1 import OVERSEER_PERFORMANCE_SERIES_VERSION_V1, load_overseer_performance_series_v1
from autotrader_overseer_performance_v1 import OVERSEER_PERFORMANCE_STRATEGY_KEY_V1
from autotrader_pnl_comparison_v2 import replay_automanager_pnl_comparison_v2
from autotrader_sfl_v1 import SFL_STRATEGY_KEYS_V1
from autotrader_sfl_series_v1 import SFL_SERIES_VERSION_V1, load_sfl_series_v1
from autotrader_shadow_leverage_v2 import apply_schedule_to_series_v2, leverage_at_v2, load_live_leverage_schedule_v2
from autotrader_strategy_catalog_v2 import AI_BASELINE_STRATEGY_V2, COCKTAIL_MODE_1_SHADOW_STRATEGY_V2, MACD_1M_FLIP_STRATEGY_V2, MACD_A_STRATEGY_V1, PAPER_30M_STRATEGIES_V2, STRONG_COCKTAIL_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2, load_active_strategy_enrollments_v2
from autotrader_strategy_series_store_v1 import StrategySeriesPointV1, ensure_strategy_series_schema_v1, make_strategy_series_identity_v1, persist_strategy_series_points_v1
from autotrader_strong_cocktail_shadow_v2 import CONFIG_VERSION as STRONG_CONFIG_VERSION
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as MACD_TRAILING_STRATEGY_KEY_V3
from autotrader_v3_macd_trailing_series_v1 import SERIES_VERSION_V3 as MACD_TRAILING_SERIES_VERSION_V3, load_macd_trailing_shadow_series_v3
from database import using_postgres

LOGGER = logging.getLogger("pricegauger.autotrader.strategy_series_materializer_v1")
DEFAULT_INTERVAL_SECONDS = 60
MACD_30M_SERIES_VERSION = "MACD-30M-12-26-9-v1"
MACD_1M_SERIES_VERSION = "MACD-1M-12-26-9-v1"

@dataclass(frozen=True, slots=True)
class StrategySeriesMaterializeSummaryV1:
    products: int
    strategies: int
    points_inserted: int
    failed_products: int

def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def strategy_series_version_v1(strategy_key: str) -> str:
    key = str(strategy_key)
    if key == AEN1_STRATEGY_KEY: return AEN1_SERIES_VERSION
    if key == MACD_TRAILING_STRATEGY_KEY_V3: return MACD_TRAILING_SERIES_VERSION_V3
    if key == OVERSEER_PERFORMANCE_STRATEGY_KEY_V1: return OVERSEER_PERFORMANCE_SERIES_VERSION_V1
    if key == STRONG_COCKTAIL_STRATEGY_V2: return str(STRONG_CONFIG_VERSION)
    if key == MACD_1M_FLIP_STRATEGY_V2: return MACD_1M_SERIES_VERSION
    if key in set(MACD_CONTROL_STRATEGY_KEYS_V1.values()): return str(MACD_TIMEFRAME_SERIES_VERSION)
    if key in set(HYBRID_STRATEGY_KEYS_V1.values()): return str(HYBRID_SERIES_VERSION_V1)
    if key in set(SFL_STRATEGY_KEYS_V1.values()): return str(SFL_SERIES_VERSION_V1)
    if key == MACD_A_STRATEGY_V1: return str(MACD_A_SERIES_VERSION_V1)
    if key == AI_BASELINE_STRATEGY_V2: return str(AI_BASELINE_FRESH_SERIES_VERSION)
    if key == COCKTAIL_MODE_1_SHADOW_STRATEGY_V2: return str(COCKTAIL_CONFIG_VERSION)
    if key in {item.key for item in PAPER_30M_STRATEGIES_V2}: return MACD_30M_SERIES_VERSION
    return f"{key}:v1"

def _product_groups_v1(enrollments: tuple[StrategyEnrollmentV2, ...]):
    groups = {}
    for item in enrollments:
        groups.setdefault((str(item.account_id), int(item.uic), str(item.asset_type), int(item.instrument_id)), []).append(item)
    return tuple(tuple(group) for group in groups.values())

def _series_points_v1(raw_series, leveraged_series, schedule):
    if len(raw_series.points) != len(leveraged_series.points): raise ValueError("raw and pilot-equivalent series have different point counts")
    seed = float(raw_series.seed_equity)
    if seed <= 0: raise ValueError("strategy series seed equity must be positive")
    points = []
    for raw, leveraged in zip(raw_series.points, leveraged_series.points):
        raw_at, leveraged_at = _utc(raw.closed_at), _utc(leveraged.closed_at)
        if raw_at != leveraged_at or raw.position_state != leveraged.position_state: raise ValueError("raw and pilot-equivalent strategy clocks are not aligned")
        raw_equity, pilot_equity = float(raw.equity), float(leveraged.equity)
        points.append(StrategySeriesPointV1(raw_at, str(raw.position_state), raw_equity, ((raw_equity / seed)-1.0)*100.0, float(leverage_at_v2(schedule, raw_at)), pilot_equity, ((pilot_equity / seed)-1.0)*100.0))
    return tuple(points)

def materialize_strategy_series_once_v1(*, db_path: str = "pricegauger.db", now: datetime | None = None) -> StrategySeriesMaterializeSummaryV1:
    if not using_postgres(): return StrategySeriesMaterializeSummaryV1(0,0,0,0)
    ensure_strategy_series_schema_v1()
    end = _utc(now or datetime.now(timezone.utc))
    groups = _product_groups_v1(tuple(item for item in load_active_strategy_enrollments_v2() if item.enabled))
    strategy_count = inserted = failed = 0
    for group in groups:
        live_items = tuple(item for item in group if item.execution_mode == EXECUTION_MODE_LIVE)
        if len(live_items) != 1: continue
        live = live_items[0]
        try:
            comparison = replay_automanager_pnl_comparison_v2(group, db_path=db_path, now=end)
            schedule = load_live_leverage_schedule_v2(pilot_key=live.pilot_key, account_id=live.account_id, uic=live.uic, asset_type=live.asset_type)
            timeframe_controls = load_macd_timeframe_control_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            hybrid_controls = load_macd_hybrid_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            sfl_controls = load_sfl_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            macd_a = load_macd_a_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            macd_trailing = load_macd_trailing_shadow_series_v3(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            aen1 = load_aen1_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            fresh_ai = load_ai_baseline_fresh_series_v1(instrument_id=live.instrument_id, seed_equity=comparison.seed_equity, currency=comparison.currency, started_at=comparison.started_at, as_of=end, db_path=db_path)
            # Preserve the explicit freshness contract: never let the legacy AI baseline carry stale exposure.
            legacy_without_ai = tuple(series for series in comparison.paper_series if str(series.strategy_key) != str(AI_BASELINE_STRATEGY_V2))
            experts = legacy_without_ai + tuple(timeframe_controls) + tuple(hybrid_controls) + tuple(sfl_controls) + (() if macd_a is None else (macd_a,)) + (() if macd_trailing is None else (macd_trailing,))
            overseer = load_overseer_performance_series_v1(experts)
            raw_model_series = experts + (() if fresh_ai is None else (fresh_ai,)) + (() if overseer is None else (overseer,)) + (() if aen1 is None else (aen1,))
            leveraged = apply_schedule_to_series_v2(raw_model_series, schedule=schedule)
            if len(leveraged) != len(raw_model_series): raise ValueError("leverage transformation changed strategy-series count")
            for raw, lev in zip(raw_model_series, leveraged):
                if raw.strategy_key != lev.strategy_key: raise ValueError("leverage transformation changed strategy identity")
                identity = make_strategy_series_identity_v1(account_id=live.account_id, uic=live.uic, asset_type=live.asset_type, instrument_id=live.instrument_id, strategy_key=raw.strategy_key, strategy_version=strategy_series_version_v1(raw.strategy_key), started_at=raw.started_at, currency=raw.currency, seed_equity=raw.seed_equity, execution_mode=raw.execution_mode)
                inserted += persist_strategy_series_points_v1(identity, _series_points_v1(raw, lev, schedule)); strategy_count += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning("strategy series materialization failed product=%s:%s:%s instrument_id=%s: %s", live.account_id, live.uic, live.asset_type, live.instrument_id, exc, exc_info=True)
    return StrategySeriesMaterializeSummaryV1(len(groups), strategy_count, inserted, failed)

def run_strategy_series_materializer_forever_v1(*, db_path: str = "pricegauger.db", interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    interval = max(30, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            summary = materialize_strategy_series_once_v1(db_path=db_path)
            if summary.points_inserted or summary.failed_products:
                LOGGER.info("strategy series bridge products=%d strategies=%d inserted=%d failed=%d", summary.products, summary.strategies, summary.points_inserted, summary.failed_products)
        except Exception as exc:
            LOGGER.warning("strategy series bridge cycle failed: %s", exc, exc_info=True)
        time.sleep(max(1.0, interval - (time.monotonic() - started)))

__all__ = ["DEFAULT_INTERVAL_SECONDS", "MACD_1M_SERIES_VERSION", "MACD_30M_SERIES_VERSION", "StrategySeriesMaterializeSummaryV1", "materialize_strategy_series_once_v1", "run_strategy_series_materializer_forever_v1", "strategy_series_version_v1"]
