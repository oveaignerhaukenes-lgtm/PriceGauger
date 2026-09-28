"""Experimental SIM replay on canonical closed bars; no order authority.

Hunter/Rabid Dog require historical bid/ask ticks and must not be inferred
from minute OHLC candles. Only MACD-A variants are replayed here.
"""
from __future__ import annotations

from collections import deque
from math import isfinite
import pandas as pd

from autotrader_hybrid_replay_v1 import _timeframe_spread
from autotrader_macd_models_v1 import adaptive_timeframe_v1
from autotrader_macd_a_extended_v1 import select_extended_macd_a
from autotrader_macd_a_pyr_v1 import Cross, PyramidState, plan_macd_a_pyramid


def replay_macd_a_variants(bars) -> dict[str, pd.DataFrame]:
    ordered = sorted(bars, key=lambda bar: bar.bar_time)
    if len(ordered) < 80:
        raise ValueError("MACD-A SIM requires at least 80 closed 1m bars")
    frame = pd.DataFrame({
        "at": [pd.Timestamp(b.bar_time) + pd.Timedelta(minutes=1) for b in ordered],
        "close": [float(b.close) for b in ordered],
    }).set_index("at").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    spreads = {m: _timeframe_spread(frame, m) for m in (1, 2, 5, 15, 30)}
    outcomes: deque[bool] = deque(maxlen=8)
    crosses: dict[int, int] = {}
    targets = {name: [] for name in ("MACD-A", "MACD-A-PYR", "MACD-A(1-30)", "MACD-A-PYR(1-30)")}
    legacy = PyramidState()
    extended = PyramidState()
    for i, at in enumerate(frame.index):
        if i:
            previous = float(spreads[1].iloc[i - 1])
            current = float(spreads[1].iloc[i])
            if previous <= 0 < current:
                crosses[i] = 1
            elif previous >= 0 > current:
                crosses[i] = -1
            origin = i - 3
            if origin in crosses:
                move = float(frame["close"].iloc[i]) - float(frame["close"].iloc[origin])
                outcomes.append(move * crosses[origin] > 0)
        edge = sum(outcomes) / len(outcomes) if len(outcomes) >= 3 else .5
        noise = 1 - edge
        if any(not isfinite(float(spreads[m].iloc[i])) for m in (1, 2, 5)):
            for values in targets.values():
                values.append(0.0)
            continue
        selected = adaptive_timeframe_v1(micro_edge=edge, noise=noise)
        spread = float(spreads[selected].iloc[i])
        direction = "LONG" if spread > 0 else "SHORT" if spread < 0 else "FLAT"
        extended_decision = select_extended_macd_a(
            {m: float(series.iloc[i]) for m, series in spreads.items() if isfinite(float(series.iloc[i]))},
            micro_edge=edge, noise=noise,
        )
        current_crosses = tuple(
            Cross(m, at, float(s.iloc[i-1]), float(s.iloc[i]))
            for m, s in spreads.items() if i and isfinite(float(s.iloc[i])) and isfinite(float(s.iloc[i-1])) and float(s.iloc[i]) != float(s.iloc[i-1])
            and (float(s.iloc[i-1]) <= 0 < float(s.iloc[i]) or float(s.iloc[i-1]) >= 0 > float(s.iloc[i]))
        )
        for name, chosen, state, enabled in (
            ("MACD-A-PYR", direction, legacy, (1, 2, 5)),
            ("MACD-A-PYR(1-30)", extended_decision.direction, extended, (1, 2, 5, 15, 30)),
        ):
            observed = state.direction if state.direction != "FLAT" else "FLAT"
            decision = plan_macd_a_pyramid(
                state=state, macd_a_direction=chosen, observed_direction=observed,
                crosses=current_crosses, enabled_timeframes=enabled,
            )
            # SIM assumes immediate fills; LIVE must reconcile broker fills.
            if decision.action == "CLOSE":
                state = PyramidState(seen_events=decision.state.seen_events)
            else:
                state = decision.state
            if name == "MACD-A-PYR":
                legacy = state
            else:
                extended = state
            target = (1 if state.direction == "LONG" else -1 if state.direction == "SHORT" else 0)
            targets[name].append(target * state.tranches / 10)
        targets["MACD-A"].append(1 if direction == "LONG" else -1 if direction == "SHORT" else 0)
        targets["MACD-A(1-30)"].append(1 if extended_decision.direction == "LONG" else -1 if extended_decision.direction == "SHORT" else 0)
    return {
        name: pd.DataFrame({"PRICE": frame["close"], "TARGET": values}, index=frame.index)
        for name, values in targets.items()
    }
