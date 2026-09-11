from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from autotrader_macd_supervisor_v1 import (
    TIMEFRAMES_V1,
    MacdTimeframeStateV1,
    evaluate_macd_supervisor_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarV2


SUPERVISOR_WARMUP_1M_ROWS_V1 = 35 * 30


@dataclass(frozen=True, slots=True)
class MacdSupervisorSwitchV1:
    at: pd.Timestamp
    price: float
    previous_target: int
    target: int
    score: float
    confidence: float
    context_score: float
    change_score: float
    explanation: str
    spreads: dict[int, float]
    slopes: dict[int, float]


@dataclass(frozen=True, slots=True)
class MacdSupervisorReplaySummaryV1:
    rows: int
    switches: int
    completed_trades: int
    win_rate_pct: float
    return_pct: float
    max_drawdown_pct: float
    capture_area_pct: float
    profitable_time_pct: float


def _macd_spread(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd - signal


def _timeframe_spread(frame: pd.DataFrame, minutes: int) -> pd.Series:
    if int(minutes) == 1:
        return _macd_spread(frame["close"])
    closed = (
        frame["close"]
        .resample(f"{int(minutes)}min", origin="epoch", label="right", closed="left")
        .last()
        .dropna()
    )
    return _macd_spread(closed).reindex(frame.index, method="ffill")


def _max_drawdown_pct(curve: pd.Series) -> float:
    equity = 1.0 + (curve / 100.0)
    peaks = equity.cummax().replace(0.0, pd.NA)
    dd = ((equity / peaks) - 1.0) * 100.0
    return float(dd.min()) if not dd.dropna().empty else 0.0


def summarize_macd_supervisor_frame_v1(
    frame: pd.DataFrame,
    *,
    cost_bps_per_leg: float = 0.0,
) -> MacdSupervisorReplaySummaryV1:
    """Score any replay slice so visible-window metrics never include hidden warmup."""
    if frame.empty or "PRICE" not in frame.columns or "TARGET" not in frame.columns:
        return MacdSupervisorReplaySummaryV1(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    equity = 1.0
    curve: list[float] = []
    cost = max(0.0, float(cost_bps_per_leg)) / 10_000.0
    active_target = int(frame["TARGET"].iloc[0])
    entry_price = float(frame["PRICE"].iloc[0]) if active_target in (-1, 1) else None
    directional_sum = 0.0
    absolute_sum = 0.0
    profitable_minutes = 0
    active_minutes = 0
    trade_results: list[float] = []
    switches = 0

    for index in range(len(frame)):
        price = float(frame["PRICE"].iloc[index])
        desired = int(frame["TARGET"].iloc[index])
        if index > 0:
            previous_price = float(frame["PRICE"].iloc[index - 1])
            minute_return = 0.0 if previous_price <= 0.0 else (price / previous_price) - 1.0
            if active_target in (-1, 1):
                equity *= 1.0 + (active_target * minute_return)
                directional_sum += active_target * minute_return
                absolute_sum += abs(minute_return)
                active_minutes += 1
                if entry_price is not None:
                    mark = active_target * ((price / entry_price) - 1.0)
                    if mark > 0.0:
                        profitable_minutes += 1
        if desired != active_target:
            switches += 1
            if active_target in (-1, 1) and entry_price is not None and entry_price > 0.0:
                trade_results.append(active_target * ((price / entry_price) - 1.0))
            legs = abs(desired - active_target)
            if legs > 0:
                equity *= max(0.0, 1.0 - (cost * legs))
            active_target = desired
            entry_price = price if desired in (-1, 1) else None
        curve.append((equity - 1.0) * 100.0)

    curve_series = pd.Series(curve, index=frame.index, dtype="float64")
    wins = sum(1 for value in trade_results if value > 0.0)
    win_rate = (wins / len(trade_results) * 100.0) if trade_results else 0.0
    capture = (directional_sum / absolute_sum * 100.0) if absolute_sum > 0.0 else 0.0
    profitable_time = (profitable_minutes / active_minutes * 100.0) if active_minutes else 0.0
    return MacdSupervisorReplaySummaryV1(
        rows=len(frame),
        switches=switches,
        completed_trades=len(trade_results),
        win_rate_pct=float(win_rate),
        return_pct=float(curve_series.iloc[-1]),
        max_drawdown_pct=_max_drawdown_pct(curve_series),
        capture_area_pct=float(capture),
        profitable_time_pct=float(profitable_time),
    )


def replay_macd_supervisor_v1(
    bars: Sequence[CanonicalMarketBarV2],
    *,
    cost_bps_per_leg: float = 0.0,
    switch_threshold: float = 0.22,
) -> tuple[pd.DataFrame, tuple[MacdSupervisorSwitchV1, ...], MacdSupervisorReplaySummaryV1]:
    """Replay the analysis-only MACD supervisor on canonical 1m data.

    capture_area_pct is signed directional movement captured divided by total absolute
    movement while the model is active. +100 means every minute's move was held in the
    correct direction, 0 means gains/losses cancel, and negative values mean the model
    spent more movement on the wrong side than the right side.
    """
    if len(bars) <= SUPERVISOR_WARMUP_1M_ROWS_V1:
        raise ValueError(
            f"MACD Supervisor Lab needs >{SUPERVISOR_WARMUP_1M_ROWS_V1} canonical 1m bars for 30m warmup"
        )

    ordered = sorted(bars, key=lambda item: item.bar_time)
    frame = pd.DataFrame(
        {
            "at": [pd.Timestamp(item.bar_time) + pd.Timedelta(minutes=1) for item in ordered],
            "close": [float(item.close) for item in ordered],
        }
    ).set_index("at")
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()

    spreads = {minutes: _timeframe_spread(frame, minutes) for minutes in TIMEFRAMES_V1}
    result = pd.DataFrame(index=frame.index)
    result["PRICE"] = frame["close"]
    target = 0
    targets: list[int] = []
    scores: list[float] = []
    confidence: list[float] = []
    switches: list[MacdSupervisorSwitchV1] = []

    for index in range(len(frame)):
        if index < SUPERVISOR_WARMUP_1M_ROWS_V1 or any(pd.isna(spreads[m].iloc[index]) for m in TIMEFRAMES_V1):
            targets.append(target)
            scores.append(0.0)
            confidence.append(0.0)
            continue
        states = {
            minutes: MacdTimeframeStateV1(
                minutes=minutes,
                spread=float(spreads[minutes].iloc[index]),
                previous_spread=float(spreads[minutes].iloc[index - 1]),
            )
            for minutes in TIMEFRAMES_V1
        }
        decision = evaluate_macd_supervisor_v1(
            states,
            current_target=target,
            switch_threshold=switch_threshold,
        )
        previous = target
        target = int(decision.target)
        if target != previous and target in (-1, 1):
            switches.append(
                MacdSupervisorSwitchV1(
                    at=pd.Timestamp(frame.index[index]),
                    price=float(frame["close"].iloc[index]),
                    previous_target=previous,
                    target=target,
                    score=float(decision.score),
                    confidence=float(decision.confidence),
                    context_score=float(decision.context_score),
                    change_score=float(decision.change_score),
                    explanation=decision.explanation,
                    spreads={m: float(states[m].spread) for m in TIMEFRAMES_V1},
                    slopes={m: float(states[m].slope) for m in TIMEFRAMES_V1},
                )
            )
        targets.append(target)
        scores.append(float(decision.score))
        confidence.append(float(decision.confidence))

    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["SCORE"] = pd.Series(scores, index=result.index, dtype="float64")
    result["CONFIDENCE"] = pd.Series(confidence, index=result.index, dtype="float64")

    # Keep a full replay curve for plotting/export; visible-card metrics are recalculated
    # from the visible slice with summarize_macd_supervisor_frame_v1.
    summary = summarize_macd_supervisor_frame_v1(result, cost_bps_per_leg=cost_bps_per_leg)
    equity = 1.0
    cost = max(0.0, float(cost_bps_per_leg)) / 10_000.0
    active_target = 0
    curve: list[float] = []
    for index in range(len(result)):
        price = float(result["PRICE"].iloc[index])
        desired = int(result["TARGET"].iloc[index])
        if index > 0 and active_target in (-1, 1):
            previous_price = float(result["PRICE"].iloc[index - 1])
            minute_return = 0.0 if previous_price <= 0.0 else (price / previous_price) - 1.0
            equity *= 1.0 + (active_target * minute_return)
        if desired != active_target:
            legs = abs(desired - active_target)
            if legs > 0:
                equity *= max(0.0, 1.0 - (cost * legs))
            active_target = desired
        curve.append((equity - 1.0) * 100.0)
    result["RETURN_PCT"] = pd.Series(curve, index=result.index, dtype="float64")
    summary = MacdSupervisorReplaySummaryV1(
        rows=summary.rows,
        switches=len(switches),
        completed_trades=summary.completed_trades,
        win_rate_pct=summary.win_rate_pct,
        return_pct=float(result["RETURN_PCT"].iloc[-1]),
        max_drawdown_pct=_max_drawdown_pct(result["RETURN_PCT"]),
        capture_area_pct=summary.capture_area_pct,
        profitable_time_pct=summary.profitable_time_pct,
    )
    return result, tuple(switches), summary


__all__ = [
    "SUPERVISOR_WARMUP_1M_ROWS_V1",
    "MacdSupervisorReplaySummaryV1",
    "MacdSupervisorSwitchV1",
    "replay_macd_supervisor_v1",
    "summarize_macd_supervisor_frame_v1",
]
