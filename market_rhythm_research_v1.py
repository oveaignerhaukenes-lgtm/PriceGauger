"""Causal, read-only research on canonical completed 1-minute OHLC bars.

No broker, database writes, strategies, orders, or model fitting on test data.
The baseline predicts *switch versus continuation*, not profitable fills.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite


@dataclass(frozen=True)
class Candle:
    at: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Pivot:
    kind: str
    label: str
    at: datetime
    confirmed_at: datetime
    price: float
    segment: int


def _utc(value: object) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("bar timestamps must include a UTC offset")
    return dt.astimezone(timezone.utc)


def clean_bars(rows: object) -> tuple[Candle, ...]:
    """Accept canonical bar records; reject invalid bars and duplicate timestamps."""
    data = []
    seen = set()
    for row in rows:
        field = (lambda name: row[name]) if isinstance(row, dict) else (lambda name: getattr(row, name))
        at = _utc(field("bar_time"))
        o, h, l, c = (float(field(name)) for name in ("open", "high", "low", "close"))
        if (at.second or at.microsecond or at in seen or not all(isfinite(x) and x > 0 for x in (o, h, l, c))
                or l > min(o, c) or h < max(o, c) or l > h):
            raise ValueError("invalid or duplicated completed 1m OHLC bar")
        seen.add(at)
        data.append(Candle(at, o, h, l, c))
    return tuple(sorted(data, key=lambda x: x.at))


def aggregate_bars(bars: tuple[Candle, ...], minutes: int) -> tuple[Candle, ...]:
    """UTC-aligned, complete buckets only: never invent bars over market closures."""
    if minutes not in (1, 2, 5, 10, 15):
        raise ValueError("timeframe must be 1, 2, 5, 10 or 15 minutes")
    if minutes == 1:
        return bars
    groups = defaultdict(list)
    for bar in bars:
        bucket = bar.at - timedelta(minutes=bar.at.minute % minutes)
        groups[bucket].append(bar)
    output = []
    one = timedelta(minutes=1)
    for start in sorted(groups):
        group = groups[start]
        if (len(group) != minutes or group[0].at != start or
                any(group[i].at != start + i * one for i in range(minutes))):
            continue
        output.append(Candle(start, group[0].open, max(x.high for x in group),
                             min(x.low for x in group), group[-1].close))
    return tuple(output)


def confirmed_pivots(bars: tuple[Candle, ...], *, minutes: int, reversal_pct: float) -> tuple[Pivot, ...]:
    """OHLC-extreme swings, confirmed by a later completed candle close.

    If a candle creates a new extreme *and* closes back through the threshold,
    its intrabar order is unknown: do not also confirm a turn on that candle.
    """
    if not 0 < reversal_pct < 100:
        raise ValueError("invalid reversal threshold")
    turns = []
    gap = timedelta(minutes=minutes)
    segment = 0
    idx = 0
    while idx < len(bars):
        stop = idx + 1
        while stop < len(bars) and bars[stop].at - bars[stop - 1].at == gap:
            stop += 1
        if stop - idx < 3:
            idx, segment = stop, segment + 1
            continue
        low = high = bars[idx]
        extreme = bars[idx]
        trend = 0
        last_peaks = {}
        eps = reversal_pct / 100.0

        def emit(kind: str, pivot: Candle, confirmed: Candle) -> None:
            price = pivot.high if kind == "PEAK" else pivot.low
            previous = last_peaks.get(kind)
            if previous is None:
                label = "START"
            elif kind == "PEAK":
                label = "HH" if price > previous else "LH" if price < previous else "EQ"
            else:
                label = "HL" if price > previous else "LL" if price < previous else "EQ"
            # bar_time marks candle OPEN; its OHLC is only known at close.
            turns.append(Pivot(kind, label, pivot.at, confirmed.at + gap, price, segment))
            last_peaks[kind] = price

        for current in bars[idx + 1:stop]:
            c = current.close
            if trend == 0:
                if current.low < low.low:
                    low = current
                if current.high > high.high:
                    high = current
                if current is not low and c >= low.low * (1 + eps):
                    emit("TROUGH", low, current)
                    trend, extreme = 1, current
                elif current is not high and c <= high.high * (1 - eps):
                    emit("PEAK", high, current)
                    trend, extreme = -1, current
            elif trend == 1:
                if current.high > extreme.high:
                    extreme = current
                elif c <= extreme.high * (1 - eps):
                    emit("PEAK", extreme, current)
                    trend, extreme = -1, current
            else:
                if current.low < extreme.low:
                    extreme = current
                elif c >= extreme.low * (1 + eps):
                    emit("TROUGH", extreme, current)
                    trend, extreme = 1, current
        idx, segment = stop, segment + 1
    return tuple(turns)


def structure_report(bars: tuple[Candle, ...], *, minutes: int, reversal_pct: float,
                     min_cases: int = 8, top: int = 20) -> dict:
    """Pattern frequencies and future returns from the *confirmation* timestamp."""
    scaled = aggregate_bars(bars, minutes)
    turns = confirmed_pivots(scaled, minutes=minutes, reversal_pct=reversal_pct)
    per_segment = defaultdict(list)
    for turn in turns:
        if turn.label not in ("HH", "HL", "LH", "LL"):
            continue
        per_segment[turn.segment].append(turn)
    price_at = {bar.at + timedelta(minutes=minutes): bar.close for bar in scaled}
    counter = defaultdict(lambda: {"n": 0, "next": Counter(), "future": defaultdict(list)})
    for events in per_segment.values():
        for i, event in enumerate(events):
            for length in (2, 3, 4):
                if i + 1 < length:
                    continue
                pattern = tuple(e.label for e in events[i + 1 - length:i + 1])
                cell = counter[pattern]
                cell["n"] += 1
                if i + 1 < len(events):
                    cell["next"][events[i + 1].label] += 1
                reference = price_at.get(event.confirmed_at)
                if reference is None:
                    continue
                for horizon in (5, 10, 20, 30):
                    future = price_at.get(event.confirmed_at + timedelta(minutes=horizon))
                    if future is not None:
                        # The exact timestamp suffices only if there are no gaps;
                        # require *every* intermediate completed scaled bar.
                        if horizon % minutes or any(
                            event.confirmed_at + timedelta(minutes=t) not in price_at
                            for t in range(minutes, horizon + 1, minutes)
                        ):
                            continue
                        cell["future"][horizon].append(100.0 * (future / reference - 1))
    patterns = []
    for pattern, cell in counter.items():
        n = cell["n"]
        if n < min_cases:
            continue
        next_n = sum(cell["next"].values())
        next_label, next_count = cell["next"].most_common(1)[0] if next_n else ("ukjent", 0)
        record = {"Sekvens": " → ".join(pattern), "Antall": n,
                  "Neste N": next_n, "Neste vanligst": next_label,
                  "Neste %": round(100 * next_count / next_n, 1) if next_n else None}
        for horizon in (5, 10, 20, 30):
            outcomes = cell["future"][horizon]
            record[f"N {horizon}m"] = len(outcomes)
            record[f"Opp {horizon}m %"] = (round(100 * sum(x > 0 for x in outcomes) / len(outcomes), 1)
                                         if outcomes else None)
            record[f"Snitt {horizon}m %"] = (round(sum(outcomes) / len(outcomes), 4)
                                           if outcomes else None)
        patterns.append(record)
    patterns.sort(key=lambda row: (-row["Antall"], row["Sekvens"]))
    return {"timeframe": minutes, "bars": len(scaled), "turns": len(turns),
            "labeled": sum(map(len, per_segment.values())),
            "coverage_from": scaled[0].at if scaled else None,
            "coverage_to": scaled[-1].at if scaled else None,
            "patterns": patterns[:top]}


def rhythm_prediction_report(bars: tuple[Candle, ...]) -> list[dict]:
    """Expanding temporal folds; mirror-invariant vs signed 1–3m features.

    Predict whether the next 1m return will change sign (not its direction).
    Input magnitudes are fixed bins (<1bp, 1–3bp, >=3bp), not test-fit.
    The training set expands at 50/60/70/80/90% of eligible observations.
    """
    if len(bars) < 120:
        return []
    changes = [None] * len(bars)
    for i in range(1, len(bars)):
        if bars[i].at - bars[i - 1].at == timedelta(minutes=1):
            ret = bars[i].close / bars[i - 1].close - 1.0
            if ret != 0.0:
                changes[i] = ret
    reports = []
    for n in (1, 2, 3):
        samples = []
        for i in range(n, len(bars) - 1):
            recent = changes[i - n + 1:i + 1]
            future = changes[i + 1]
            if any(x is None for x in recent) or future is None:
                continue
            signs = tuple(1 if x > 0 else -1 for x in recent)
            relative = tuple(sign * signs[-1] for sign in signs)
            bins = tuple(0 if abs(x) < .0001 else 1 if abs(x) < .0003 else 2 for x in recent)
            switched = int((future > 0) != (recent[-1] > 0))
            samples.append(((relative, bins), (signs, bins), switched))
        if len(samples) < 120:
            continue
        predictions = {"Nullmodell": [], "Speilsymmetrisk": [], "Retningsspesifikk": []}
        outcomes = []
        total = len(samples)
        for fold in range(5, 10):
            start, end = fold * total // 10, (fold + 1) * total // 10
            train, test = samples[:start], samples[start:end]
            if not test:
                continue
            base = (sum(row[2] for row in train) + 1) / (len(train) + 2)
            histories = {}
            for name, key_at in (("Speilsymmetrisk", 0), ("Retningsspesifikk", 1)):
                groups = defaultdict(lambda: [0, 0])
                for row in train:
                    entry = groups[row[key_at]]
                    entry[0] += row[2]
                    entry[1] += 1
                histories[name] = (key_at, groups)
            for row in test:
                outcomes.append(row[2])
                predictions["Nullmodell"].append(base)
                for name, (key_at, groups) in histories.items():
                    yes, count = groups[row[key_at]]
                    predictions[name].append((yes + 16 * base) / (count + 16))
        if not outcomes:
            continue
        result = {"Historikk": f"{n}m", "Testpunkter": len(outcomes),
                  "Faktisk retningsskifte %": round(100 * sum(outcomes) / len(outcomes), 1)}
        for name, probs in predictions.items():
            hit = sum(int(p >= .5) == actual for p, actual in zip(probs, outcomes)) / len(outcomes)
            brier = sum((p - actual) ** 2 for p, actual in zip(probs, outcomes)) / len(outcomes)
            result[f"{name} treff %"] = round(100 * hit, 2)
            result[f"{name} Brier"] = round(brier, 5)
        reports.append(result)
    return reports
