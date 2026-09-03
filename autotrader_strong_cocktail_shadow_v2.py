from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable

from autotrader_cocktail_mode_1_shadow_v2 import STRATEGY_KEY as COCKTAIL_MODE_1_STRATEGY_KEY
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from database import connect
from trading_desk import ChartBar
from trading_desk_indicators import calculate_indicators


STRONG_COCKTAIL_STRATEGY_KEY = "strong-cocktail-shadow-v1"
MACD_1M_CONTROL_STRATEGY_KEY = "macd-1m-flip-control-shadow-v1"
CONFIG_VERSION = "SC-2026-09-03-v2"
SOURCE_KIND = "COCKTAIL_SAMPLES_PLUS_CANONICAL_1M"
MAX_GAP_MINUTES = 3.0
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
WARMUP_MINUTES = 180


@dataclass(frozen=True, slots=True)
class StrongCocktailEvidenceV1:
    action_at: datetime
    price: float
    cross_1m: str | None
    spread_1m: float
    velocity_1m_atr: float
    move_3m_atr1: float
    move_5m_atr1: float
    efficiency_5m: float
    structure_direction: str | None
    activity_z: float
    range_ratio_1m: float
    break_direction: str | None
    shock_direction: str | None
    whipsaw: bool
    data_gap: bool
    spread_5m: float
    spread_10m: float
    spread_15m: float
    spread_30m: float


@dataclass(frozen=True, slots=True)
class _CocktailSampleV1:
    action_at: datetime
    price: float
    activity_z: float
    range_ratio_1m: float
    efficiency_5m: float
    break_direction: str | None
    shock_direction: str | None
    whipsaw: bool
    data_gap: bool
    spread_5m: float
    spread_10m: float
    spread_15m: float
    spread_30m: float


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _sign_direction(value: float, *, epsilon: float = 1e-12) -> str | None:
    if float(value) > epsilon:
        return STATE_LONG
    if float(value) < -epsilon:
        return STATE_SHORT
    return None


def _opposite(direction: str) -> str:
    if direction == STATE_LONG:
        return STATE_SHORT
    if direction == STATE_SHORT:
        return STATE_LONG
    raise ValueError(f"direction has no opposite: {direction}")


def _efficiency(closes: Iterable[float]) -> float:
    values = tuple(float(item) for item in closes)
    if len(values) < 2:
        return 0.0
    net = abs(values[-1] - values[0])
    path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if path <= 1e-12:
        return 0.0
    return min(1.0, max(0.0, net / path))


def _context_score(direction: str, evidence: StrongCocktailEvidenceV1) -> float:
    score = 0.0
    for spread, weight in (
        (evidence.spread_5m, 2.0),
        (evidence.spread_10m, 1.5),
        (evidence.spread_15m, 1.0),
        (evidence.spread_30m, 1.0),
    ):
        observed = _sign_direction(spread)
        if observed == direction:
            score += weight
        elif observed == _opposite(direction):
            score -= weight
    return score


def _strong_event_direction(evidence: StrongCocktailEvidenceV1) -> str | None:
    price_direction = _sign_direction(evidence.move_3m_atr1)
    if price_direction is None:
        return None
    if _sign_direction(evidence.spread_1m) != price_direction:
        return None
    if _sign_direction(evidence.velocity_1m_atr) != price_direction:
        return None
    impulse = abs(float(evidence.move_3m_atr1)) >= 1.0
    structure = (
        evidence.structure_direction == price_direction
        or evidence.break_direction == price_direction
        or evidence.shock_direction == price_direction
    )
    activity = (
        float(evidence.activity_z) >= 1.0
        or float(evidence.range_ratio_1m) >= 1.25
    )
    efficient = float(evidence.efficiency_5m) >= 0.45
    if impulse and efficient and (structure or activity):
        return price_direction
    if (
        structure
        and abs(float(evidence.move_3m_atr1)) >= 0.70
        and float(evidence.efficiency_5m) >= 0.60
    ):
        return price_direction
    return None


def _normal_entry_direction(evidence: StrongCocktailEvidenceV1) -> str | None:
    direction = evidence.cross_1m
    if direction not in {STATE_LONG, STATE_SHORT}:
        return None
    if _sign_direction(evidence.move_3m_atr1) != direction:
        return None
    if abs(float(evidence.move_3m_atr1)) < 0.25:
        return None
    if _sign_direction(evidence.velocity_1m_atr) != direction:
        return None
    if _context_score(direction, evidence) < -1.5:
        return None
    price_qualifier = (
        evidence.structure_direction == direction
        or evidence.break_direction == direction
        or abs(float(evidence.move_5m_atr1)) >= 0.50
        or float(evidence.range_ratio_1m) >= 1.0
    )
    return direction if price_qualifier else None


def _continuation_entry_direction(evidence: StrongCocktailEvidenceV1) -> str | None:
    """Re-enter an established fast move after an early exposure-reducing exit.

    A normal adverse 1m cross can deliberately flatten an existing position before
    Strong Cocktail has enough evidence to commit to the opposite side. That cross is
    already gone on the following bar, so requiring a second cross would strand the
    strategy FLAT for the rest of an otherwise clean move. Continuation entry therefore
    uses persistent 1m momentum + price direction, with stricter evidence than the exit
    gate and without bypassing the outer WHIPSAW/data-gap gates.
    """
    direction = _sign_direction(evidence.spread_1m)
    if direction not in {STATE_LONG, STATE_SHORT}:
        return None
    if _sign_direction(evidence.velocity_1m_atr) != direction:
        return None
    if _sign_direction(evidence.move_3m_atr1) != direction:
        return None
    if abs(float(evidence.move_3m_atr1)) < 0.35:
        return None
    if float(evidence.efficiency_5m) < 0.50:
        return None
    if _context_score(direction, evidence) < -1.0:
        return None
    price_qualifier = (
        evidence.structure_direction == direction
        or evidence.break_direction == direction
        or evidence.shock_direction == direction
        or abs(float(evidence.move_5m_atr1)) >= 0.55
        or float(evidence.range_ratio_1m) >= 1.05
        or float(evidence.activity_z) >= 0.50
    )
    return direction if price_qualifier else None


def strong_cocktail_target_v1(
    current_state: str,
    evidence: StrongCocktailEvidenceV1,
) -> str:
    """Fast-event/slow-context shadow policy.

    Price and 1m momentum may remove exposure early. Higher horizons qualify confidence
    instead of acting as sequential cross gates. This function has no execution authority.
    """
    if current_state not in {STATE_FLAT, STATE_LONG, STATE_SHORT}:
        raise ValueError(f"unsupported Strong Cocktail state: {current_state}")
    if evidence.data_gap:
        return STATE_FLAT

    strong = _strong_event_direction(evidence)
    if evidence.whipsaw and strong is None:
        return STATE_FLAT

    if current_state != STATE_FLAT:
        counter = _opposite(current_state)
        if strong == counter:
            return counter
        price_counter = _sign_direction(evidence.move_3m_atr1) == counter
        fast_counter = _sign_direction(evidence.velocity_1m_atr) == counter
        if (
            price_counter
            and fast_counter
            and abs(float(evidence.move_3m_atr1)) >= 0.75
        ):
            return STATE_FLAT
        if evidence.cross_1m == counter and price_counter:
            return STATE_FLAT
        return current_state

    if strong is not None:
        return strong
    normal = _normal_entry_direction(evidence)
    if normal is not None:
        return normal
    continuation = _continuation_entry_direction(evidence)
    return STATE_FLAT if continuation is None else continuation


def macd_1m_control_target_v1(
    current_state: str,
    *,
    cross_1m: str | None,
    data_gap: bool,
) -> str:
    """Minimal control: flip LONG/SHORT only on a contiguous 1m MACD 12/26/9 cross."""
    if current_state not in {STATE_FLAT, STATE_LONG, STATE_SHORT}:
        raise ValueError(f"unsupported 1m control state: {current_state}")
    if data_gap:
        return current_state
    if cross_1m == STATE_LONG:
        return STATE_LONG
    if cross_1m == STATE_SHORT:
        return STATE_SHORT
    return current_state


def _load_cocktail_samples_v1(
    *,
    instrument_id: int,
    started_at: datetime,
    as_of: datetime,
) -> tuple[_CocktailSampleV1, ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT action_at, price, activity_z, range_ratio_1m, efficiency_5m,
                   break_direction, shock_direction, whipsaw, data_gap,
                   spread_5m, spread_10m, spread_15m, spread_30m
            FROM pg_v2_autotrader_cocktail_mode_1_samples
            WHERE strategy_key=? AND instrument_id=? AND action_at>=? AND action_at<=?
            ORDER BY action_at ASC
            """,
            (
                COCKTAIL_MODE_1_STRATEGY_KEY,
                int(instrument_id),
                _utc(started_at),
                _utc(as_of),
            ),
        ).fetchall()
    materialized: list[_CocktailSampleV1] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0],
            "price": row[1],
            "activity_z": row[2],
            "range_ratio_1m": row[3],
            "efficiency_5m": row[4],
            "break_direction": row[5],
            "shock_direction": row[6],
            "whipsaw": row[7],
            "data_gap": row[8],
            "spread_5m": row[9],
            "spread_10m": row[10],
            "spread_15m": row[11],
            "spread_30m": row[12],
        }
        materialized.append(
            _CocktailSampleV1(
                action_at=_utc(values["action_at"]),
                price=float(values["price"]),
                activity_z=float(values["activity_z"]),
                range_ratio_1m=float(values["range_ratio_1m"]),
                efficiency_5m=float(values["efficiency_5m"]),
                break_direction=None if values["break_direction"] is None else str(values["break_direction"]),
                shock_direction=None if values["shock_direction"] is None else str(values["shock_direction"]),
                whipsaw=bool(values["whipsaw"]),
                data_gap=bool(values["data_gap"]),
                spread_5m=float(values["spread_5m"]),
                spread_10m=float(values["spread_10m"]),
                spread_15m=float(values["spread_15m"]),
                spread_30m=float(values["spread_30m"]),
            )
        )
    return tuple(materialized)


def _chart_bars(bars: Iterable[CanonicalMarketBarV2]) -> tuple[ChartBar, ...]:
    return tuple(
        ChartBar(
            market=str(item.market_name),
            bar_time=str(item.bar_time),
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=None if item.volume is None else float(item.volume),
        )
        for item in bars
    )


def _fast_evidence_by_action_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    samples: tuple[_CocktailSampleV1, ...],
) -> dict[datetime, StrongCocktailEvidenceV1]:
    if len(bars) < 40 or not samples:
        return {}
    chart = _chart_bars(bars)
    indicators = calculate_indicators(
        chart,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
    )
    macd = {_utc(item.bar_time): float(item.value) for item in indicators.macd}
    signal = {_utc(item.bar_time): float(item.value) for item in indicators.macd_signal}
    atr = {_utc(item.bar_time): float(item.value) for item in indicators.atr}
    sample_by_action = {item.action_at: item for item in samples}

    evidence: dict[datetime, StrongCocktailEvidenceV1] = {}
    spreads: dict[datetime, float] = {}
    for index, bar in enumerate(bars):
        bar_at = _utc(bar.bar_time)
        action_at = _action_at(bar)
        sample = sample_by_action.get(action_at)
        macd_value = macd.get(bar_at)
        signal_value = signal.get(bar_at)
        atr_value = atr.get(bar_at)
        if macd_value is None or signal_value is None or atr_value is None or atr_value <= 0:
            continue
        spread = float(macd_value - signal_value)
        spreads[action_at] = spread
        if sample is None:
            continue

        previous_action = _action_at(bars[index - 1]) if index > 0 else None
        previous_spread = spreads.get(previous_action) if previous_action is not None else None
        data_gap = bool(sample.data_gap)
        if previous_action is not None:
            data_gap = data_gap or (
                (action_at - previous_action).total_seconds() / 60.0 > MAX_GAP_MINUTES
            )

        cross = None
        if not data_gap and previous_spread is not None:
            if previous_spread <= 0.0 < spread:
                cross = STATE_LONG
            elif previous_spread >= 0.0 > spread:
                cross = STATE_SHORT

        velocity = 0.0 if previous_spread is None else (spread - previous_spread) / max(float(atr_value), 1e-12)

        def normalized_move(lookback: int) -> float:
            if index < lookback:
                return 0.0
            prior = bars[index - lookback]
            elapsed = (action_at - _action_at(prior)).total_seconds() / 60.0
            if elapsed > float(lookback) + MAX_GAP_MINUTES:
                return 0.0
            return (float(bar.close) - float(prior.close)) / max(float(atr_value), 1e-12)

        move3 = normalized_move(3)
        move5 = normalized_move(5)
        close_window = tuple(float(item.close) for item in bars[max(0, index - 5): index + 1])
        fast_efficiency = _efficiency(close_window)

        structure = None
        if index >= 5:
            reference = bars[index - 5:index]
            prior_high = max(float(item.high) for item in reference)
            prior_low = min(float(item.low) for item in reference)
            if float(bar.close) > prior_high:
                structure = STATE_LONG
            elif float(bar.close) < prior_low:
                structure = STATE_SHORT

        evidence[action_at] = StrongCocktailEvidenceV1(
            action_at=action_at,
            price=float(sample.price),
            cross_1m=cross,
            spread_1m=spread,
            velocity_1m_atr=float(velocity),
            move_3m_atr1=float(move3),
            move_5m_atr1=float(move5),
            efficiency_5m=max(float(sample.efficiency_5m), float(fast_efficiency)),
            structure_direction=structure,
            activity_z=float(sample.activity_z),
            range_ratio_1m=float(sample.range_ratio_1m),
            break_direction=sample.break_direction,
            shock_direction=sample.shock_direction,
            whipsaw=bool(sample.whipsaw),
            data_gap=bool(data_gap),
            spread_5m=float(sample.spread_5m),
            spread_10m=float(sample.spread_10m),
            spread_15m=float(sample.spread_15m),
            spread_30m=float(sample.spread_30m),
        )
    return evidence


def _series_from_evidence_v1(
    evidence: tuple[StrongCocktailEvidenceV1, ...],
    *,
    seed_equity: float,
    currency: str,
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    if not evidence:
        return ()
    seed = float(seed_equity)
    if not math.isfinite(seed) or seed <= 0:
        raise ValueError("seed_equity must be finite and positive")

    strong_equity = seed
    control_equity = seed
    strong_state = STATE_FLAT
    control_state = STATE_FLAT
    strong_points = [
        ShadowEquityPointV2(
            closed_at=evidence[0].action_at,
            equity=seed,
            position_state=strong_state,
        )
    ]
    control_points = [
        ShadowEquityPointV2(
            closed_at=evidence[0].action_at,
            equity=seed,
            position_state=control_state,
        )
    ]
    prior_price = float(evidence[0].price)

    for item in evidence[1:]:
        if prior_price <= 0 or float(item.price) <= 0:
            raise ValueError("Strong Cocktail shadow price must be positive")
        price_return = (float(item.price) / prior_price) - 1.0
        strong_equity = apply_shadow_return_v2(
            equity=strong_equity,
            position_state=strong_state,
            price_return=price_return,
        )
        control_equity = apply_shadow_return_v2(
            equity=control_equity,
            position_state=control_state,
            price_return=price_return,
        )
        if strong_equity <= 0:
            strong_state = STATE_FLAT
        else:
            strong_state = strong_cocktail_target_v1(strong_state, item)
        if control_equity <= 0:
            control_state = STATE_FLAT
        else:
            control_state = macd_1m_control_target_v1(
                control_state,
                cross_1m=item.cross_1m,
                data_gap=item.data_gap,
            )
        strong_points.append(
            ShadowEquityPointV2(
                closed_at=item.action_at,
                equity=float(strong_equity),
                position_state=strong_state,
            )
        )
        control_points.append(
            ShadowEquityPointV2(
                closed_at=item.action_at,
                equity=float(control_equity),
                position_state=control_state,
            )
        )
        prior_price = float(item.price)

    started = evidence[0].action_at
    return (
        ShadowBenchmarkSeriesV2(
            strategy_key=STRONG_COCKTAIL_STRATEGY_KEY,
            execution_mode="SHADOW_ADAPTIVE",
            currency=str(currency),
            seed_equity=seed,
            started_at=started,
            points=tuple(strong_points),
        ),
        ShadowBenchmarkSeriesV2(
            strategy_key=MACD_1M_CONTROL_STRATEGY_KEY,
            execution_mode="SHADOW_CONTROL",
            currency=str(currency),
            seed_equity=seed,
            started_at=started,
            points=tuple(control_points),
        ),
    )


def load_strong_cocktail_comparison_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str = "pricegauger.db",
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    """Return Strong Cocktail and its simple 1m MACD control on one common clock.

    Both series start FLAT at the first persisted Cocktail Mode #1 sample. No historical
    pre-deployment crosses are replayed, and neither series has execution authority.
    """
    samples = _load_cocktail_samples_v1(
        instrument_id=int(instrument_id),
        started_at=_utc(started_at),
        as_of=_utc(as_of),
    )
    if not samples:
        return ()
    store = CanonicalMarketBarStoreV2(db_path)
    bars = store.load_instrument_range(
        instrument_id=int(instrument_id),
        start=samples[0].action_at - timedelta(minutes=WARMUP_MINUTES),
        end=_utc(as_of),
        limit=BENCHMARK_MAX_1M_BARS,
    )
    evidence_by_action = _fast_evidence_by_action_v1(tuple(bars), samples)
    evidence = tuple(
        evidence_by_action[item.action_at]
        for item in samples
        if item.action_at in evidence_by_action
    )
    if not evidence:
        return ()
    series = _series_from_evidence_v1(
        evidence,
        seed_equity=float(seed_equity),
        currency=str(currency),
    )
    return tuple(series)


__all__ = [
    "CONFIG_VERSION",
    "MACD_1M_CONTROL_STRATEGY_KEY",
    "SOURCE_KIND",
    "STRONG_COCKTAIL_STRATEGY_KEY",
    "StrongCocktailEvidenceV1",
    "load_strong_cocktail_comparison_series_v1",
    "macd_1m_control_target_v1",
    "strong_cocktail_target_v1",
]
