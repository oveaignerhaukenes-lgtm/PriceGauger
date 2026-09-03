from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

from autotrader_ai_baseline_v1 import PROMPT_VERSION as AI_PROMPT_VERSION
from autotrader_cocktail_mode_1_shadow_v2 import CONFIG_VERSION as COCKTAIL_CONFIG_VERSION
from autotrader_pnl_comparison_v2 import load_automanager_pnl_comparison_v2
from autotrader_shadow_leverage_v2 import (
    apply_schedule_to_series_v2,
    leverage_at_v2,
    load_live_leverage_schedule_v2,
)
from autotrader_strategy_catalog_v2 import (
    AI_BASELINE_STRATEGY_V2,
    COCKTAIL_MODE_1_SHADOW_STRATEGY_V2,
    MACD_1M_FLIP_STRATEGY_V2,
    PAPER_30M_STRATEGIES_V2,
    STRONG_COCKTAIL_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
)
from autotrader_strategy_series_store_v1 import (
    StrategySeriesPointV1,
    ensure_strategy_series_schema_v1,
    make_strategy_series_identity_v1,
    persist_strategy_series_points_v1,
)
from autotrader_strong_cocktail_shadow_v2 import CONFIG_VERSION as STRONG_CONFIG_VERSION
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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def strategy_series_version_v1(strategy_key: str) -> str:
    key = str(strategy_key)
    if key == STRONG_COCKTAIL_STRATEGY_V2:
        return str(STRONG_CONFIG_VERSION)
    if key == MACD_1M_FLIP_STRATEGY_V2:
        return MACD_1M_SERIES_VERSION
    if key == AI_BASELINE_STRATEGY_V2:
        return str(AI_PROMPT_VERSION)
    if key == COCKTAIL_MODE_1_SHADOW_STRATEGY_V2:
        return str(COCKTAIL_CONFIG_VERSION)
    if key in {item.key for item in PAPER_30M_STRATEGIES_V2}:
        return MACD_30M_SERIES_VERSION
    # The bridge is intentionally conservative: unknown strategy semantics are not
    # silently mixed with another version. The strategy key remains a stable version
    # token until that producer exposes an explicit config version.
    return f"{key}:v1"


def _product_groups_v1(
    enrollments: tuple[StrategyEnrollmentV2, ...],
) -> tuple[tuple[StrategyEnrollmentV2, ...], ...]:
    groups: dict[tuple[str, int, str, int], list[StrategyEnrollmentV2]] = {}
    for item in enrollments:
        key = (
            str(item.account_id),
            int(item.uic),
            str(item.asset_type),
            int(item.instrument_id),
        )
        groups.setdefault(key, []).append(item)
    return tuple(tuple(group) for group in groups.values())


def _series_points_v1(raw_series, leveraged_series, schedule) -> tuple[StrategySeriesPointV1, ...]:
    if len(raw_series.points) != len(leveraged_series.points):
        raise ValueError("raw and pilot-equivalent series have different point counts")
    seed = float(raw_series.seed_equity)
    if seed <= 0:
        raise ValueError("strategy series seed equity must be positive")
    points: list[StrategySeriesPointV1] = []
    for raw, leveraged in zip(raw_series.points, leveraged_series.points):
        raw_at = _utc(raw.closed_at)
        leveraged_at = _utc(leveraged.closed_at)
        if raw_at != leveraged_at or raw.position_state != leveraged.position_state:
            raise ValueError("raw and pilot-equivalent strategy clocks are not aligned")
        raw_equity = float(raw.equity)
        pilot_equity = float(leveraged.equity)
        points.append(
            StrategySeriesPointV1(
                observed_at=raw_at,
                position_state=str(raw.position_state),
                equity_1x=raw_equity,
                return_pct_1x=((raw_equity / seed) - 1.0) * 100.0,
                effective_leverage=float(leverage_at_v2(schedule, raw_at)),
                equity_pilot_equivalent=pilot_equity,
                return_pct_pilot_equivalent=((pilot_equity / seed) - 1.0) * 100.0,
            )
        )
    return tuple(points)


def materialize_strategy_series_once_v1(
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> StrategySeriesMaterializeSummaryV1:
    """Bridge current model engines into one durable Strategy Lab series contract.

    This is deliberately a migration bridge. Existing model functions remain the
    source of truth today, but their replay work runs in the background and the UI can
    later read only persisted points. Native model producers can replace the bridge one
    at a time without changing the stored chart/query contract.
    """
    if not using_postgres():
        return StrategySeriesMaterializeSummaryV1(0, 0, 0, 0)
    ensure_strategy_series_schema_v1()
    end = _utc(now or datetime.now(timezone.utc))
    active = tuple(item for item in load_active_strategy_enrollments_v2() if item.enabled)
    groups = _product_groups_v1(active)
    strategy_count = 0
    inserted = 0
    failed = 0

    for group in groups:
        live_items = tuple(item for item in group if item.execution_mode == EXECUTION_MODE_LIVE)
        if len(live_items) != 1:
            continue
        live = live_items[0]
        try:
            comparison = load_automanager_pnl_comparison_v2(group, db_path=db_path, now=end)
            schedule = load_live_leverage_schedule_v2(
                pilot_key=live.pilot_key,
                account_id=live.account_id,
                uic=live.uic,
                asset_type=live.asset_type,
            )
            leveraged = apply_schedule_to_series_v2(comparison.paper_series, schedule=schedule)
            if len(leveraged) != len(comparison.paper_series):
                raise ValueError("leverage transformation changed strategy-series count")
            for raw_series, leveraged_series in zip(comparison.paper_series, leveraged):
                if raw_series.strategy_key != leveraged_series.strategy_key:
                    raise ValueError("leverage transformation changed strategy identity")
                identity = make_strategy_series_identity_v1(
                    account_id=live.account_id,
                    uic=live.uic,
                    asset_type=live.asset_type,
                    instrument_id=live.instrument_id,
                    strategy_key=raw_series.strategy_key,
                    strategy_version=strategy_series_version_v1(raw_series.strategy_key),
                    started_at=raw_series.started_at,
                    currency=raw_series.currency,
                    seed_equity=raw_series.seed_equity,
                    execution_mode=raw_series.execution_mode,
                )
                points = _series_points_v1(raw_series, leveraged_series, schedule)
                inserted += persist_strategy_series_points_v1(identity, points)
                strategy_count += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "strategy series materialization failed product=%s:%s:%s instrument_id=%s: %s",
                live.account_id,
                live.uic,
                live.asset_type,
                live.instrument_id,
                exc,
                exc_info=True,
            )

    return StrategySeriesMaterializeSummaryV1(
        products=len(groups),
        strategies=strategy_count,
        points_inserted=inserted,
        failed_products=failed,
    )


def run_strategy_series_materializer_forever_v1(
    *,
    db_path: str = "pricegauger.db",
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    interval = max(30, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            summary = materialize_strategy_series_once_v1(db_path=db_path)
            if summary.points_inserted or summary.failed_products:
                LOGGER.info(
                    "strategy series bridge products=%d strategies=%d inserted=%d failed=%d",
                    summary.products,
                    summary.strategies,
                    summary.points_inserted,
                    summary.failed_products,
                )
        except Exception as exc:
            LOGGER.warning("strategy series bridge cycle failed: %s", exc, exc_info=True)
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "MACD_1M_SERIES_VERSION",
    "MACD_30M_SERIES_VERSION",
    "StrategySeriesMaterializeSummaryV1",
    "materialize_strategy_series_once_v1",
    "run_strategy_series_materializer_forever_v1",
    "strategy_series_version_v1",
]
