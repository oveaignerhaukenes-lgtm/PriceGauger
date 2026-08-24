from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from threading import Lock
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_managed_positions_v1 import (
    load_active_managed_positions_v1,
    managed_position_matches_v1,
)
from autotrader_schema_v2 import DEFAULT_HARD_STOP_PCT, ensure_autotrader_schema_v2
from database import connect, using_postgres
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.risk_control_v2")
STRATEGY_KEY = "risk-control-v2"
DEFAULT_PORTFOLIO_OBSERVATION_SECONDS = 10
DEFAULT_MANAGED_RISK_REACTION_SECONDS = 2
_RISK_CYCLE_LOCK = Lock()
ACTION_HOLD = "HOLD"
ACTION_WOULD_CLOSE = "WOULD_CLOSE"
REASON_HARD_STOP = "HARD_STOP"
REASON_TRAILING_STOP = "TRAILING_STOP"
REASON_FIXED_TAKE_PROFIT = "FIXED_TAKE_PROFIT"
REASON_DISABLED = "DISABLED"
REASON_NOT_CLOSEABLE = "NOT_CLOSEABLE"
REASON_UNRELIABLE = "UNRELIABLE_PRICE"
REASON_PRICE_DELAYED = "PRICE_DELAYED"
REASON_MARKET_CLOSED = "MARKET_CLOSED"
REASON_NON_TRADABLE = "NON_TRADABLE"


@dataclass(frozen=True, slots=True)
class RiskConfigV2:
    enabled: bool = True
    hard_stop_pct: float = DEFAULT_HARD_STOP_PCT
    trailing_enabled: bool = True
    trailing_activation_pct: float = 2.0
    trailing_drawdown_pct: float = 0.5
    fixed_take_profit_enabled: bool = False
    fixed_take_profit_pct: float = 5.0
    max_price_delay_minutes: int = 0


@dataclass(frozen=True, slots=True)
class PositionObservationV2:
    account_id: str
    net_position_id: str
    uic: int
    asset_type: str
    direction: str
    amount: float
    average_open_price: float
    current_price: float
    pnl_pct: float
    price_delay_minutes: int
    can_be_closed: bool
    calculation_reliability: str
    is_market_open: bool = True
    non_tradable_reason: str = "None"


@dataclass(frozen=True, slots=True)
class RiskDecisionV2:
    action: str
    reason: str
    pnl_pct: float
    high_water_pct: float
    trailing_floor_pct: float | None
    eligible_for_execution: bool


@dataclass(frozen=True, slots=True)
class RiskCycleSummaryV2:
    observed: int
    close_signals: int
    failed: int


def _validate_config(config: RiskConfigV2) -> RiskConfigV2:
    if float(config.hard_stop_pct) >= 0:
        raise ValueError("hard_stop_pct must be below 0")
    if float(config.trailing_activation_pct) <= 0:
        raise ValueError("trailing_activation_pct must be above 0")
    if float(config.trailing_drawdown_pct) <= 0:
        raise ValueError("trailing_drawdown_pct must be above 0")
    if float(config.fixed_take_profit_pct) <= 0:
        raise ValueError("fixed_take_profit_pct must be above 0")
    if int(config.max_price_delay_minutes) < 0:
        raise ValueError("max_price_delay_minutes cannot be negative")
    return config


def ensure_risk_control_schema_v2() -> None:
    """Initialize the complete canonical AutoTrader v2 persistence boundary."""
    ensure_autotrader_schema_v2()


def load_risk_config_v2() -> RiskConfigV2:
    with connect() as db:
        row = db.execute(
            """
            SELECT enabled, hard_stop_pct, trailing_enabled,
                   trailing_activation_pct, trailing_drawdown_pct,
                   fixed_take_profit_enabled, fixed_take_profit_pct,
                   max_price_delay_minutes
            FROM pg_v2_autotrader_risk_config
            WHERE config_id = 1
            """
        ).fetchone()
    if row is None:
        return RiskConfigV2()
    values = list(row.values()) if isinstance(row, dict) else list(row)
    return _validate_config(
        RiskConfigV2(
            enabled=bool(values[0]),
            hard_stop_pct=float(values[1]),
            trailing_enabled=bool(values[2]),
            trailing_activation_pct=float(values[3]),
            trailing_drawdown_pct=float(values[4]),
            fixed_take_profit_enabled=bool(values[5]),
            fixed_take_profit_pct=float(values[6]),
            max_price_delay_minutes=int(values[7]),
        )
    )


def save_risk_config_v2(config: RiskConfigV2) -> RiskConfigV2:
    config = _validate_config(config)
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_risk_config SET
                enabled = ?, hard_stop_pct = ?, trailing_enabled = ?,
                trailing_activation_pct = ?, trailing_drawdown_pct = ?,
                fixed_take_profit_enabled = ?, fixed_take_profit_pct = ?,
                max_price_delay_minutes = ?, updated_at = now()
            WHERE config_id = 1
            """,
            (
                bool(config.enabled),
                float(config.hard_stop_pct),
                bool(config.trailing_enabled),
                float(config.trailing_activation_pct),
                float(config.trailing_drawdown_pct),
                bool(config.fixed_take_profit_enabled),
                float(config.fixed_take_profit_pct),
                int(config.max_price_delay_minutes),
            ),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_risk_state
            SET triggered_reason = NULL, triggered_at = NULL,
                last_action = 'HOLD', last_reason = 'CONFIG_CHANGED', updated_at = now()
            """
        )
    return config


def pnl_percent_v2(*, average_open_price: float, current_price: float, direction: str) -> float:
    """Return position return in percent of the traded product price.

    This deliberately does not express return on account equity, margin or underlying
    market movement. For a bought short/bear product the opening direction is still
    Buy, so the product's own price movement remains the risk-control reference.
    """
    opening = float(average_open_price)
    current = float(current_price)
    if opening <= 0 or current <= 0:
        raise ValueError("prices must be above 0")
    side = str(direction).strip().lower()
    if side == "buy":
        sign = 1.0
    elif side == "sell":
        sign = -1.0
    else:
        raise ValueError(f"unsupported opening direction: {direction}")
    return ((current - opening) / opening) * 100.0 * sign


def _tradable_reason_is_clear(reason: str) -> bool:
    return str(reason or "").strip().lower() in {"", "none"}


def evaluate_risk_v2(
    observation: PositionObservationV2,
    *,
    config: RiskConfigV2,
    previous_high_water_pct: float | None = None,
    already_triggered_reason: str | None = None,
) -> RiskDecisionV2:
    config = _validate_config(config)
    high_water = max(
        float(observation.pnl_pct),
        float(previous_high_water_pct) if previous_high_water_pct is not None else float(observation.pnl_pct),
    )
    trailing_floor = None
    if config.trailing_enabled and high_water >= config.trailing_activation_pct:
        trailing_floor = high_water - config.trailing_drawdown_pct

    if already_triggered_reason:
        return RiskDecisionV2(
            action=ACTION_WOULD_CLOSE,
            reason=str(already_triggered_reason),
            pnl_pct=observation.pnl_pct,
            high_water_pct=high_water,
            trailing_floor_pct=trailing_floor,
            eligible_for_execution=False,
        )

    if not config.enabled:
        reason = REASON_DISABLED
    elif not observation.can_be_closed:
        reason = REASON_NOT_CLOSEABLE
    elif not observation.is_market_open:
        reason = REASON_MARKET_CLOSED
    elif not _tradable_reason_is_clear(observation.non_tradable_reason):
        reason = REASON_NON_TRADABLE
    elif observation.calculation_reliability.strip().lower() not in {"ok", ""}:
        reason = REASON_UNRELIABLE
    elif observation.price_delay_minutes > config.max_price_delay_minutes:
        reason = REASON_PRICE_DELAYED
    elif observation.pnl_pct <= config.hard_stop_pct:
        return RiskDecisionV2(
            action=ACTION_WOULD_CLOSE,
            reason=REASON_HARD_STOP,
            pnl_pct=observation.pnl_pct,
            high_water_pct=high_water,
            trailing_floor_pct=trailing_floor,
            eligible_for_execution=True,
        )
    elif config.fixed_take_profit_enabled and observation.pnl_pct >= config.fixed_take_profit_pct:
        return RiskDecisionV2(
            action=ACTION_WOULD_CLOSE,
            reason=REASON_FIXED_TAKE_PROFIT,
            pnl_pct=observation.pnl_pct,
            high_water_pct=high_water,
            trailing_floor_pct=trailing_floor,
            eligible_for_execution=True,
        )
    elif trailing_floor is not None and observation.pnl_pct <= trailing_floor:
        return RiskDecisionV2(
            action=ACTION_WOULD_CLOSE,
            reason=REASON_TRAILING_STOP,
            pnl_pct=observation.pnl_pct,
            high_water_pct=high_water,
            trailing_floor_pct=trailing_floor,
            eligible_for_execution=True,
        )
    else:
        reason = ACTION_HOLD

    return RiskDecisionV2(
        action=ACTION_HOLD,
        reason=reason,
        pnl_pct=observation.pnl_pct,
        high_water_pct=high_water,
        trailing_floor_pct=trailing_floor,
        eligible_for_execution=False,
    )


def _position_observations_v2(client) -> tuple[PositionObservationV2, ...]:
    payload = client._get("port/v1/netpositions/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo net positions response had invalid Data format")
    observations: list[PositionObservationV2] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        base = row.get("NetPositionBase") if isinstance(row.get("NetPositionBase"), dict) else {}
        view = row.get("NetPositionView") if isinstance(row.get("NetPositionView"), dict) else {}
        status = str(view.get("Status") or base.get("SinglePositionStatus") or "")
        amount = float(base.get("Amount") or 0.0)
        if status.lower() not in {"open", ""} or amount == 0.0:
            continue
        net_position_id = str(row.get("NetPositionId") or "").strip()
        account_id = str(base.get("PositionsAccount") or base.get("AccountId") or "").strip()
        direction = str(base.get("OpeningDirection") or ("Buy" if amount > 0 else "Sell"))
        opening = float(view.get("AverageOpenPriceIncludingCosts") or view.get("AverageOpenPrice") or 0.0)
        current = float(view.get("CurrentPrice") or 0.0)
        if not net_position_id or not account_id or opening <= 0 or current <= 0:
            continue
        observations.append(
            PositionObservationV2(
                account_id=account_id,
                net_position_id=net_position_id,
                uic=int(base.get("Uic") or -1),
                asset_type=str(base.get("AssetType") or ""),
                direction=direction,
                amount=abs(amount),
                average_open_price=opening,
                current_price=current,
                pnl_pct=pnl_percent_v2(
                    average_open_price=opening,
                    current_price=current,
                    direction=direction,
                ),
                price_delay_minutes=int(view.get("CurrentPriceDelayMinutes") or 0),
                can_be_closed=bool(base.get("CanBeClosed", False)),
                calculation_reliability=str(view.get("CalculationReliability") or ""),
                is_market_open=bool(base.get("IsMarketOpen", False)),
                non_tradable_reason=str(base.get("NonTradableReason") or ""),
            )
        )
    return tuple(observations)


def _load_previous_state(account_id: str, net_position_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT average_open_price, direction, high_water_pct, triggered_reason,
                   triggered_at, active
            FROM pg_v2_autotrader_risk_state
            WHERE account_id = ? AND net_position_id = ?
            """,
            (account_id, net_position_id),
        ).fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {
        "average_open_price": row[0],
        "direction": row[1],
        "high_water_pct": row[2],
        "triggered_reason": row[3],
        "triggered_at": row[4],
        "active": row[5],
    }


def _persist_observation(
    observation: PositionObservationV2,
    decision: RiskDecisionV2,
    *,
    config: RiskConfigV2,
    previous_triggered_reason: str | None,
    previous_triggered_at: datetime | None,
) -> None:
    now = datetime.now(timezone.utc)
    new_trigger = decision.action == ACTION_WOULD_CLOSE and previous_triggered_reason is None
    trigger_reason = decision.reason if decision.action == ACTION_WOULD_CLOSE else None
    trigger_at = now if new_trigger else (previous_triggered_at if previous_triggered_reason else None)
    with connect() as db:
        if new_trigger:
            identity = (
                f"{STRATEGY_KEY}|{observation.account_id}|{observation.net_position_id}|"
                f"{decision.reason}|{now.isoformat()}"
            )
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_risk_events
                    (event_id, account_id, net_position_id, uic, asset_type, direction,
                     reason, pnl_pct, high_water_pct, trailing_floor_pct,
                     hard_stop_pct, trailing_activation_pct, trailing_drawdown_pct,
                     fixed_take_profit_pct, price_delay_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid5(NAMESPACE_URL, identity)), observation.account_id,
                    observation.net_position_id, observation.uic, observation.asset_type,
                    observation.direction, decision.reason, decision.pnl_pct,
                    decision.high_water_pct, decision.trailing_floor_pct,
                    config.hard_stop_pct, config.trailing_activation_pct,
                    config.trailing_drawdown_pct, config.fixed_take_profit_pct,
                    observation.price_delay_minutes,
                ),
            )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_risk_state
                (account_id, net_position_id, uic, asset_type, direction, amount,
                 average_open_price, current_price, pnl_pct, high_water_pct,
                 trailing_floor_pct, price_delay_minutes, can_be_closed,
                 calculation_reliability, is_market_open, non_tradable_reason,
                 last_action, last_reason, triggered_reason, triggered_at,
                 active, last_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, now(), now())
            ON CONFLICT (account_id, net_position_id) DO UPDATE SET
                uic = EXCLUDED.uic, asset_type = EXCLUDED.asset_type,
                direction = EXCLUDED.direction, amount = EXCLUDED.amount,
                average_open_price = EXCLUDED.average_open_price,
                current_price = EXCLUDED.current_price, pnl_pct = EXCLUDED.pnl_pct,
                high_water_pct = EXCLUDED.high_water_pct,
                trailing_floor_pct = EXCLUDED.trailing_floor_pct,
                price_delay_minutes = EXCLUDED.price_delay_minutes,
                can_be_closed = EXCLUDED.can_be_closed,
                calculation_reliability = EXCLUDED.calculation_reliability,
                is_market_open = EXCLUDED.is_market_open,
                non_tradable_reason = EXCLUDED.non_tradable_reason,
                last_action = EXCLUDED.last_action, last_reason = EXCLUDED.last_reason,
                triggered_reason = EXCLUDED.triggered_reason,
                triggered_at = EXCLUDED.triggered_at, active = TRUE,
                last_seen_at = now(), updated_at = now()
            """,
            (
                observation.account_id, observation.net_position_id, observation.uic,
                observation.asset_type, observation.direction, observation.amount,
                observation.average_open_price, observation.current_price,
                observation.pnl_pct, decision.high_water_pct, decision.trailing_floor_pct,
                observation.price_delay_minutes, observation.can_be_closed,
                observation.calculation_reliability, observation.is_market_open,
                observation.non_tradable_reason, decision.action, decision.reason,
                trigger_reason, trigger_at,
            ),
        )


def _evaluate_observations_v2(
    observations: tuple[PositionObservationV2, ...],
    *,
    config: RiskConfigV2,
    deactivate_missing: bool,
) -> RiskCycleSummaryV2:
    seen = {(item.account_id, item.net_position_id) for item in observations}
    close_signals = 0
    failed = 0
    for observation in observations:
        try:
            previous = _load_previous_state(observation.account_id, observation.net_position_id)
            previous_high = None
            previous_triggered = None
            previous_triggered_at = None
            if previous:
                same_basis = (
                    bool(previous.get("active"))
                    and abs(float(previous["average_open_price"]) - observation.average_open_price) < 1e-12
                    and str(previous["direction"]).lower() == observation.direction.lower()
                )
                if same_basis:
                    previous_high = float(previous["high_water_pct"])
                    previous_triggered = previous.get("triggered_reason")
                    previous_triggered_at = previous.get("triggered_at")
            decision = evaluate_risk_v2(
                observation,
                config=config,
                previous_high_water_pct=previous_high,
                already_triggered_reason=previous_triggered,
            )
            _persist_observation(
                observation,
                decision,
                config=config,
                previous_triggered_reason=previous_triggered,
                previous_triggered_at=previous_triggered_at,
            )
            if decision.action == ACTION_WOULD_CLOSE:
                close_signals += 1
                LOGGER.warning(
                    "risk control position=%s uic=%s position_return=%.3f%% high=%.3f%% action=%s reason=%s eligible=%s",
                    observation.net_position_id, observation.uic, observation.pnl_pct,
                    decision.high_water_pct, decision.action, decision.reason,
                    decision.eligible_for_execution,
                )
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "risk control position failed id=%s: %s",
                observation.net_position_id, exc, exc_info=True,
            )
    if deactivate_missing:
        with connect() as db:
            db.execute("UPDATE pg_v2_autotrader_risk_state SET active = FALSE")
            for account_id, net_position_id in seen:
                db.execute(
                    "UPDATE pg_v2_autotrader_risk_state SET active = TRUE WHERE account_id = ? AND net_position_id = ?",
                    (account_id, net_position_id),
                )
    return RiskCycleSummaryV2(
        observed=len(observations),
        close_signals=close_signals,
        failed=failed,
    )


def run_risk_control_cycle_v2() -> RiskCycleSummaryV2:
    """Observe the complete portfolio at the normal, lower-frequency cadence."""
    with _RISK_CYCLE_LOCK:
        config = load_risk_config_v2()
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
        return _evaluate_observations_v2(
            observations,
            config=config,
            deactivate_missing=True,
        )


def run_managed_risk_reaction_cycle_v2() -> RiskCycleSummaryV2:
    """Re-evaluate only exact Auto-managed positions on the fast reaction path.

    The database enrollment is read before resolving the Saxo client. With no active
    enrollments this cycle performs no Saxo request.
    """
    with _RISK_CYCLE_LOCK:
        enrollments = load_active_managed_positions_v1()
        if not enrollments:
            return RiskCycleSummaryV2(observed=0, close_signals=0, failed=0)

        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        current = {
            (item.account_id, item.net_position_id): item
            for item in _position_observations_v2(client)
        }
        managed_observations: list[PositionObservationV2] = []
        for enrollment in enrollments:
            identity = (
                str(enrollment.get("account_id") or ""),
                str(enrollment.get("net_position_id") or ""),
            )
            observation = current.get(identity)
            if observation is not None and managed_position_matches_v1(enrollment, observation):
                managed_observations.append(observation)

        return _evaluate_observations_v2(
            tuple(managed_observations),
            config=load_risk_config_v2(),
            deactivate_missing=False,
        )


def run_risk_control_forever_v2(
    *,
    interval_seconds: int = DEFAULT_PORTFOLIO_OBSERVATION_SECONDS,
) -> None:
    interval = max(5, int(interval_seconds))
    ensure_risk_control_schema_v2()
    while True:
        started_at = time.monotonic()
        try:
            summary = run_risk_control_cycle_v2()
            LOGGER.info(
                "risk portfolio cycle observed=%d close_signals=%d failed=%d",
                summary.observed, summary.close_signals, summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("risk portfolio cycle failed before position evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(
            started_at=started_at,
            interval_seconds=interval,
        )


def run_managed_risk_reaction_forever_v2(
    *,
    interval_seconds: int = DEFAULT_MANAGED_RISK_REACTION_SECONDS,
) -> None:
    interval = max(1, int(interval_seconds))
    ensure_risk_control_schema_v2()
    while True:
        started_at = time.monotonic()
        try:
            summary = run_managed_risk_reaction_cycle_v2()
            if summary.close_signals or summary.failed:
                LOGGER.info(
                    "managed risk reaction observed=%d close_signals=%d failed=%d",
                    summary.observed, summary.close_signals, summary.failed,
                )
            else:
                LOGGER.debug(
                    "managed risk reaction observed=%d close_signals=0 failed=0",
                    summary.observed,
                )
        except Exception as exc:
            LOGGER.exception("managed risk reaction failed before position evaluation: %s", exc)
        sleep_to_fixed_start_cadence_v2(
            started_at=started_at,
            interval_seconds=interval,
        )
