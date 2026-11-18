"""Causal, market-independent state quantization for read-only research.

Every state uses 61 contiguous *completed* 1m closes (60 log returns).
The model describes observed direction, micro-rhythm, and amplitude; it does
not infer Saxo fills, predict prices, fit strategies or authorize orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np
import pandas as pd


LOOKBACK_RETURNS = 60
SAMPLE_STEP_MINUTES = 5
TREND_ENTER_EFFICIENCY = 0.35
TREND_EXIT_EFFICIENCY = 0.25

TREND_LABELS = ("NED", "SIDEVEIS", "OPP")
RHYTHM_LABELS = ("RASK", "MIDDELS", "LANGSOM")


@dataclass(frozen=True)
class MarketModelSpecV1:
    key: str
    name: str
    source: str
    status: str


MARKET_MODEL_CATALOG_V1 = (
    MarketModelSpecV1(
        "coupled_strings_state_v1",
        "Koblede markedsstrenger · tilstandsmodell v1",
        "Eksakt Saxo-UIC · fullførte kanoniske 1m-barer",
        "DESKRIPTIV · PAPER-FORSKNING",
    ),
)


@dataclass(frozen=True)
class MarketStateV1:
    as_of: pd.Timestamp  # Earliest point at which the final 1m close is known.
    bar_at: pd.Timestamp  # Opening timestamp of the last completed 1m bar.
    trend: str
    rhythm: str
    state_key: str
    efficiency: float
    net_change_pct: float
    volatility_pct_1m: float
    median_abs_change_pct_1m: float
    median_run_minutes: float | None
    direction_changes: int
    rhythm_evidence: str


def _validated_closes(closes: pd.Series) -> pd.Series:
    if not isinstance(closes, pd.Series) or not isinstance(closes.index, pd.DatetimeIndex):
        raise ValueError("completed prices need a datetime-indexed Series")
    stamps = pd.to_datetime(closes.index, utc=True)
    if stamps.has_duplicates or not stamps.is_monotonic_increasing:
        raise ValueError("canonical timestamps must be sorted and unique")
    if any(t.second or t.microsecond for t in stamps):
        raise ValueError("canonical prices must use exact UTC minute timestamps")
    numbers = pd.to_numeric(closes, errors="coerce").to_numpy(dtype=float)
    if not np.all(np.isfinite(numbers) & (numbers > 0)):
        raise ValueError("canonical closes must be positive and finite")
    return pd.Series(numbers, index=stamps, dtype=float)


def _median_runs(returns: np.ndarray) -> tuple[float | None, int]:
    """Completed sign runs only; first/last runs are boundary-censored.

    Near-zero moves do not create fake turns. Runs include elapsed minutes
    spent near zero, while neither direction nor duration is invented in a gap.
    """
    absolute = np.abs(returns)
    deadband = max(1e-12, float(np.median(absolute)) * 0.1)
    signs = np.where(returns > deadband, 1, np.where(returns < -deadband, -1, 0))
    completed_runs: list[int] = []
    direction = 0
    duration = 0
    changes = 0
    for sign in signs:
        if direction == 0:
            if sign:
                direction = int(sign)
                duration = 1
            continue
        if not sign or sign == direction:
            duration += 1
        else:
            completed_runs.append(duration)
            direction = int(sign)
            duration = 1
            changes += 1
    # First run starts at a sampling boundary; the last has not ended yet.
    complete_interior = completed_runs[1:]
    return (float(np.median(complete_interior)) if len(complete_interior) >= 2 else None,
            changes)


def _trend_label(net: float, efficiency: float, previous: MarketStateV1 | None) -> str:
    if previous is not None and previous.trend in ("OPP", "NED"):
        old_sign = 1 if previous.trend == "OPP" else -1
        if net * old_sign > 0 and efficiency >= TREND_EXIT_EFFICIENCY:
            return previous.trend
    if efficiency >= TREND_ENTER_EFFICIENCY:
        return "OPP" if net > 0 else "NED"
    return "SIDEVEIS"


def _rhythm_label(median_run: float | None, previous: MarketStateV1 | None) -> str:
    if median_run is None:
        return "LANGSOM"  # Explicitly LOW evidence, not an inferred long cycle.
    if previous is not None:
        if previous.rhythm == "RASK" and median_run <= 1.8:
            return "RASK"
        if previous.rhythm == "LANGSOM" and median_run >= 3.0:
            return "LANGSOM"
    if median_run <= 1.5:
        return "RASK"
    if median_run >= 3.5:
        return "LANGSOM"
    return "MIDDELS"


def quantize_market_state_v1(
    completed_closes: pd.Series, *, previous: MarketStateV1 | None = None,
) -> MarketStateV1 | None:
    """Return UNKNOWN (None) for incomplete windows, gaps or frozen prices.

    `previous` is a strictly earlier state used only for threshold hysteresis.
    Future returns, hindsight pivots and the current forming bar are excluded.
    """
    values = _validated_closes(completed_closes)
    if len(values) != LOOKBACK_RETURNS + 1:
        return None
    if previous is not None and previous.as_of >= values.index[-1] + pd.Timedelta(minutes=1):
        raise ValueError("hysteresis state must be known strictly before current state")
    differences = values.index[1:] - values.index[:-1]
    if not np.all(differences == pd.Timedelta(minutes=1)):
        return None
    returns = np.diff(np.log(values.to_numpy(dtype=float)))
    total_motion = float(np.abs(returns).sum())
    if not isfinite(total_motion) or total_motion <= 1e-12:
        return None
    net = float(returns.sum())
    efficiency = float(np.clip(abs(net) / total_motion, 0.0, 1.0))
    median_run, direction_changes = _median_runs(returns)
    trend = _trend_label(net, efficiency, previous)
    rhythm = _rhythm_label(median_run, previous)
    last_bar = values.index[-1]
    return MarketStateV1(
        as_of=last_bar + pd.Timedelta(minutes=1), bar_at=last_bar,
        trend=trend, rhythm=rhythm, state_key=f"{trend}/{rhythm}",
        efficiency=efficiency,
        net_change_pct=float(100 * (np.exp(net) - 1)),
        volatility_pct_1m=float(100 * np.std(returns)),
        median_abs_change_pct_1m=float(100 * np.median(np.abs(returns))),
        median_run_minutes=median_run,
        direction_changes=direction_changes,
        rhythm_evidence="MÅLT" if median_run is not None else "SVAK / INGEN FULL SYKLUS",
    )


def market_state_history_v1(
    completed_closes: pd.Series, *, step_minutes: int = SAMPLE_STEP_MINUTES,
) -> tuple[MarketStateV1, ...]:
    """As-of chronology, with no hysteresis carried across missing-minute gaps."""
    if step_minutes not in (1, 2, 5, 10, 15):
        raise ValueError("supported retrospective sampling: 1/2/5/10/15m")
    values = _validated_closes(completed_closes)
    if len(values) <= LOOKBACK_RETURNS:
        return ()
    times = values.index
    observations: list[MarketStateV1] = []
    previous: MarketStateV1 | None = None
    for end in range(LOOKBACK_RETURNS, len(values)):
        if (end != len(values) - 1 and times[end].minute % step_minutes != 0):
            continue
        block = values.iloc[end - LOOKBACK_RETURNS:end + 1]
        if (block.index[-1] - block.index[0] != pd.Timedelta(minutes=LOOKBACK_RETURNS)):
            previous = None
            continue
        if previous is not None and block.index[-1] - previous.bar_at > pd.Timedelta(minutes=step_minutes + 1):
            previous = None
        observed = quantize_market_state_v1(block, previous=previous)
        if observed is not None:
            observations.append(observed)
        previous = observed
    return tuple(observations)
