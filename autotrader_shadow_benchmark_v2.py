from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from uuid import NAMESPACE_URL, uuid5

from autotrader_macd_dry_run_v2 import (
    SIGNAL_DOWN,
    SIGNAL_UP,
    closed_30m_bars_v2,
    macd_observations_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_catalog_v2 import MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2, load_active_strategy_enrollments_v2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect


LOGGER = logging.getLogger("pricegauger.autotrader.shadow_benchmark_v2")
STATE_FLAT = "FLAT"
STATE_LONG = "LONG"
STATE_SHORT = "SHORT"
SUPPORTED_STATES = {STATE_FLAT, STATE_LONG, STATE_SHORT}


@dataclass(frozen=True, slots=True)
class ShadowBenchmarkStateV2:
    pilot_key: str
    strategy_key: str
    currency: str
    seed_equity: float
    equity: float
    position_state: str
    last_bar_time: datetime
    last_close: float
    transitions: int

    @property
    def return_pct(self) -> float:
        return ((self.equity / self.seed_equity) - 1.0) * 100.0


@dataclass(frozen=True, slots=True)
class ShadowBenchmarkCycleSummaryV2:
    attempted: int
    evaluated: int
    advanced_bars: int
    failed: int


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_for_regime(strategy_key: str, spread: float) -> str:
    if spread > 0.0:
        return STATE_LONG
    if spread < 0.0 and strategy_key == MACD_FLIP_STRATEGY_V2:
        return STATE_SHORT
    return STATE_FLAT


def target_state_for_signal_v2(strategy_key: str, signal: str) -> str:
    if strategy_key not in {MACD_FLIP_STRATEGY_V2, MACD_LONG_FLAT_STRATEGY_V2}:
        raise ValueError(f"unsupported shadow strategy: {strategy_key}")
    if signal == SIGNAL_UP:
        return STATE_LONG
    if signal == SIGNAL_DOWN:
        return STATE_SHORT if strategy_key == MACD_FLIP_STRATEGY_V2 else STATE_FLAT
    raise ValueError(f"unsupported MACD signal: {signal}")


def _cross(previous_spread: float, current_spread: float) -> str | None:
    if previous_spread <= 0.0 < current_spread:
        return SIGNAL_UP
    if previous_spread >= 0.0 > current_spread:
        return SIGNAL_DOWN
    return None


def apply_shadow_return_v2(*, equity: float, position_state: str, price_return: float) -> float:
    if position_state not in SUPPORTED_STATES:
        raise ValueError(f"unsupported shadow state: {position_state}")
    if not math.isfinite(float(equity)) or float(equity) < 0:
        raise ValueError("shadow equity must be finite and non-negative")
    if not math.isfinite(float(price_return)):
        raise ValueError("price_return must be finite")
    if position_state == STATE_FLAT:
        return float(equity)
    signed_return = float(price_return) if position_state == STATE_LONG else -float(price_return)
    resulting = float(equity) * (1.0 + signed_return)
    # This is a strategy benchmark, not a margin engine. Once the normalized
    # benchmark is exhausted it stays at zero rather than inventing credit.
    return max(0.0, resulting)


def load_shadow_benchmark_state_v2(pilot_key: str) -> ShadowBenchmarkStateV2 | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, strategy_key, currency, seed_equity, equity,
                   position_state, last_bar_time, last_close, transitions
            FROM pg_v2_autotrader_shadow_benchmark_state
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "pilot_key": row[0],
        "strategy_key": row[1],
        "currency": row[2],
        "seed_equity": row[3],
        "equity": row[4],
        "position_state": row[5],
        "last_bar_time": row[6],
        "last_close": row[7],
        "transitions": row[8],
    }
    return ShadowBenchmarkStateV2(
        pilot_key=str(values["pilot_key"]),
        strategy_key=str(values["strategy_key"]),
        currency=str(values["currency"]),
        seed_equity=float(values["seed_equity"]),
        equity=float(values["equity"]),
        position_state=str(values["position_state"]),
        last_bar_time=_utc(values["last_bar_time"]),
        last_close=float(values["last_close"]),
        transitions=int(values["transitions"]),
    )


def _persist_bootstrap_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    currency: str,
    seed_equity: float,
    position_state: str,
    bar_time: datetime,
    close: float,
) -> ShadowBenchmarkStateV2:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_shadow_benchmark_state(
                pilot_key, strategy_key, market_id, instrument_id, currency,
                seed_equity, equity, position_state, last_bar_time, last_close,
                transitions, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, now())
            ON CONFLICT (pilot_key) DO NOTHING
            """,
            (
                enrollment.pilot_key,
                enrollment.strategy_key,
                enrollment.market_id,
                enrollment.instrument_id,
                currency,
                float(seed_equity),
                float(seed_equity),
                position_state,
                bar_time,
                float(close),
            ),
        )
    state = load_shadow_benchmark_state_v2(enrollment.pilot_key)
    if state is None:
        raise RuntimeError("shadow benchmark bootstrap did not persist")
    return state


def _persist_step_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    prior: ShadowBenchmarkStateV2,
    bar_time: datetime,
    close: float,
    signal: str | None,
    next_state: str,
    equity_after: float,
) -> ShadowBenchmarkStateV2:
    price_return = (float(close) / float(prior.last_close)) - 1.0
    transition = next_state != prior.position_state
    event_id = str(uuid5(NAMESPACE_URL, f"shadow-benchmark|{enrollment.pilot_key}|{bar_time.isoformat()}"))
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_shadow_benchmark_events(
                event_id, pilot_key, strategy_key, bar_time, signal,
                prior_state, next_state, prior_close, close, price_return,
                equity_before, equity_after, transitioned, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event_id,
                enrollment.pilot_key,
                enrollment.strategy_key,
                bar_time,
                signal,
                prior.position_state,
                next_state,
                prior.last_close,
                float(close),
                price_return,
                prior.equity,
                float(equity_after),
                bool(transition),
            ),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_shadow_benchmark_state
            SET equity = ?, position_state = ?, last_bar_time = ?, last_close = ?,
                transitions = transitions + ?, updated_at = now()
            WHERE pilot_key = ? AND last_bar_time = ?
            """,
            (
                float(equity_after),
                next_state,
                bar_time,
                float(close),
                1 if transition else 0,
                enrollment.pilot_key,
                prior.last_bar_time,
            ),
        )
    state = load_shadow_benchmark_state_v2(enrollment.pilot_key)
    if state is None:
        raise RuntimeError("shadow benchmark state disappeared")
    return state


def evaluate_shadow_enrollment_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
) -> int:
    """Advance one strategy benchmark using exact canonical closed 30m product bars.

    The benchmark intentionally ignores transaction costs, margin and slippage. It is
    a normalized strategy-logic comparison only. Real money P/L remains exclusively
    in the authoritative execution reconciliation ledger.
    """
    if enrollment.strategy_key not in {MACD_FLIP_STRATEGY_V2, MACD_LONG_FLAT_STRATEGY_V2}:
        raise ValueError(f"unsupported shadow strategy: {enrollment.strategy_key}")
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    end = end.astimezone(timezone.utc)
    start = end - timedelta(days=14)
    canonical = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=enrollment.instrument_id,
        start=start,
        end=end,
        limit=50000,
    )
    points = tuple(item.point for item in canonical)
    if not points:
        raise ValueError("shadow benchmark has no exact canonical 1m history")
    closed = closed_30m_bars_v2(points, market=enrollment.market_name)
    observations = macd_observations_v2(closed)
    if len(observations) < 2:
        raise ValueError("shadow benchmark needs enough history for MACD 12/26/9")
    close_by_time = {_utc(bar.bar_time): float(bar.close) for bar in closed}

    state = load_shadow_benchmark_state_v2(enrollment.pilot_key)
    if state is None:
        ledger = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        latest = observations[-1]
        close = close_by_time.get(latest.bar_time)
        if close is None or close <= 0:
            raise ValueError("shadow benchmark bootstrap close is unavailable")
        state = _persist_bootstrap_v2(
            enrollment,
            currency=ledger.currency,
            seed_equity=ledger.seed_capital,
            position_state=_state_for_regime(enrollment.strategy_key, latest.spread),
            bar_time=latest.bar_time,
            close=close,
        )
        return 0

    observations_by_time = {item.bar_time: item for item in observations}
    ordered_times = [item.bar_time for item in observations]
    if state.last_bar_time not in observations_by_time:
        raise ValueError("shadow benchmark last bar fell outside retained MACD history")
    start_index = ordered_times.index(state.last_bar_time)
    advanced = 0
    for index in range(start_index + 1, len(ordered_times)):
        previous = observations_by_time[ordered_times[index - 1]]
        current = observations_by_time[ordered_times[index]]
        close = close_by_time.get(current.bar_time)
        if close is None or close <= 0:
            raise ValueError("shadow benchmark close is unavailable")
        price_return = (close / state.last_close) - 1.0
        equity_after = apply_shadow_return_v2(
            equity=state.equity,
            position_state=state.position_state,
            price_return=price_return,
        )
        signal = _cross(previous.spread, current.spread)
        next_state = state.position_state
        if equity_after <= 0:
            next_state = STATE_FLAT
        elif signal is not None:
            next_state = target_state_for_signal_v2(enrollment.strategy_key, signal)
        state = _persist_step_v2(
            enrollment,
            prior=state,
            bar_time=current.bar_time,
            close=close,
            signal=signal,
            next_state=next_state,
            equity_after=equity_after,
        )
        advanced += 1
    return advanced


def run_shadow_benchmark_cycle_v2(*, db_path: str = "pricegauger.db") -> ShadowBenchmarkCycleSummaryV2:
    ensure_autotrader_schema_v2()
    enrollments = load_active_strategy_enrollments_v2()
    evaluated = 0
    advanced = 0
    failed = 0
    for enrollment in enrollments:
        try:
            advanced += evaluate_shadow_enrollment_once_v2(enrollment, db_path=db_path)
            evaluated += 1
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "AutoTrader shadow benchmark failed pilot=%s strategy=%s: %s",
                enrollment.pilot_key,
                enrollment.strategy_key,
                exc,
                exc_info=True,
            )
    return ShadowBenchmarkCycleSummaryV2(
        attempted=len(enrollments),
        evaluated=evaluated,
        advanced_bars=advanced,
        failed=failed,
    )


def run_shadow_benchmark_forever_v2(*, db_path: str = "pricegauger.db", interval_seconds: int = 60) -> None:
    interval = max(30, int(interval_seconds))
    while True:
        summary = run_shadow_benchmark_cycle_v2(db_path=db_path)
        LOGGER.info(
            "AutoTrader shadow benchmark attempted=%d evaluated=%d advanced_bars=%d failed=%d",
            summary.attempted,
            summary.evaluated,
            summary.advanced_bars,
            summary.failed,
        )
        time.sleep(interval)


__all__ = [
    "ShadowBenchmarkCycleSummaryV2",
    "ShadowBenchmarkStateV2",
    "apply_shadow_return_v2",
    "evaluate_shadow_enrollment_once_v2",
    "load_shadow_benchmark_state_v2",
    "run_shadow_benchmark_cycle_v2",
    "run_shadow_benchmark_forever_v2",
    "target_state_for_signal_v2",
]
