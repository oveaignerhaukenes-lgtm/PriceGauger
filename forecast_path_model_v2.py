from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Mapping


_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "10m": 10 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}


@dataclass(frozen=True, slots=True)
class ForecastPathV2:
    points: tuple[tuple[float, float], ...]
    rationale: str
    phases: tuple[str, ...] = ()
    source_timeframe: str | None = None
    expected_low_return: float | None = None
    expected_high_return: float | None = None


def _direction_sign(value: str | None) -> int:
    normalized = str(value or "").upper()
    if normalized in {"BULLISH", "HH_HL"}:
        return 1
    if normalized in {"BEARISH", "LH_LL"}:
        return -1
    return 0


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _pick_snapshot(state: Any, horizon_seconds: int) -> tuple[str, Mapping[str, Any]] | tuple[None, None]:
    snapshots = getattr(state, "snapshots", None)
    if not isinstance(snapshots, Mapping) or not snapshots:
        return None, None

    available: list[tuple[str, Mapping[str, Any], int]] = []
    for timeframe, raw in snapshots.items():
        seconds = _TIMEFRAME_SECONDS.get(str(timeframe))
        mapping = _as_mapping(raw)
        if seconds is not None and mapping is not None:
            available.append((str(timeframe), mapping, seconds))
    if not available:
        return None, None

    # Aim for roughly eight bars inside the forecast horizon so the phase model
    # uses a timeframe that can actually resolve the expected sequence.
    target_seconds = max(60.0, float(horizon_seconds) / 8.0)
    timeframe, mapping, _ = min(available, key=lambda item: (abs(item[2] - target_seconds), item[2]))
    return timeframe, mapping


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        lower, upper = upper, lower
    return max(lower, min(upper, value))


def _level_aware_range(
    *,
    snapshot: Mapping[str, Any],
    source_timeframe: str,
    horizon_seconds: int,
    expected_return: float,
    lower_return: float,
    upper_return: float,
) -> tuple[float, float]:
    timeframe_seconds = _TIMEFRAME_SECONDS[source_timeframe]
    bars = max(1.0, float(horizon_seconds) / float(timeframe_seconds))

    atr_pct = _finite_float(snapshot.get("atr_14_pct"))
    atr_return = max(0.0, (atr_pct or 0.0) / 100.0)
    horizon_budget = atr_return * sqrt(bars)

    interval_down = max(0.0, -float(lower_return))
    interval_up = max(0.0, float(upper_return))
    fallback_budget = max(
        horizon_budget,
        min(max(interval_down, interval_up), 0.004),
        abs(float(expected_return)),
        0.0005,
    )

    support_distance_pct = _finite_float(snapshot.get("distance_to_support_pct"))
    resistance_distance_pct = _finite_float(snapshot.get("distance_to_resistance_pct"))
    support_return = None if support_distance_pct is None else -max(0.0, support_distance_pct / 100.0)
    resistance_return = None if resistance_distance_pct is None else max(0.0, resistance_distance_pct / 100.0)

    raw_low = support_return if support_return is not None else -fallback_budget
    raw_high = resistance_return if resistance_return is not None else fallback_budget

    # Local extrema are computed over a longer lookback than many forecast horizons.
    # ATR therefore caps how much of a distant level is treated as expected route.
    atr_cap = max(fallback_budget, horizon_budget * 1.35, 0.00075)
    raw_low = max(raw_low, -atr_cap)
    raw_high = min(raw_high, atr_cap)

    low_bound = min(float(lower_return), 0.0)
    high_bound = max(float(upper_return), 0.0)
    low = _clamp(raw_low, low_bound, 0.0)
    high = _clamp(raw_high, 0.0, high_bound)

    minimum_excursion = min(
        max(fallback_budget * 0.55, 0.00035),
        max(interval_down, interval_up, 0.00035),
    )
    if abs(low) < minimum_excursion and interval_down >= minimum_excursion:
        low = -minimum_excursion
    if abs(high) < minimum_excursion and interval_up >= minimum_excursion:
        high = minimum_excursion
    return low, high


def _momentum_dynamics(snapshot: Mapping[str, Any]) -> tuple[int, bool, str]:
    """Return short-term direction, exhaustion flag and concise evidence text."""
    rsi = _finite_float(snapshot.get("rsi_14"))
    rsi_change = _finite_float(snapshot.get("rsi_change_3"))
    histogram = _finite_float(snapshot.get("macd_histogram"))
    histogram_change = _finite_float(snapshot.get("macd_histogram_change_3"))
    recent_return = _finite_float(snapshot.get("recent_return_3_pct"))

    direction = 0
    evidence: list[str] = []
    if histogram is not None and abs(histogram) > 1e-12:
        direction = 1 if histogram > 0 else -1
        evidence.append("MACD positiv" if direction > 0 else "MACD negativ")
    elif recent_return is not None and abs(recent_return) >= 0.02:
        direction = 1 if recent_return > 0 else -1

    exhaustion = False
    if direction > 0:
        hot = rsi is not None and rsi >= 68.0
        cooling_macd = histogram_change is not None and histogram_change < 0
        cooling_rsi = rsi_change is not None and rsi_change < -1.0
        exhaustion = bool(hot and (cooling_macd or cooling_rsi))
        if hot:
            evidence.append(f"RSI {rsi:.0f}")
        if cooling_macd:
            evidence.append("MACD kjølner")
        if cooling_rsi:
            evidence.append("RSI faller")
    elif direction < 0:
        stretched = rsi is not None and rsi <= 32.0
        cooling_macd = histogram_change is not None and histogram_change > 0
        recovering_rsi = rsi_change is not None and rsi_change > 1.0
        exhaustion = bool(stretched and (cooling_macd or recovering_rsi))
        if stretched:
            evidence.append(f"RSI {rsi:.0f}")
        if cooling_macd:
            evidence.append("bearish MACD kjølner")
        if recovering_rsi:
            evidence.append("RSI løfter")

    return direction, exhaustion, ", ".join(evidence)


def build_forecast_path_v2(
    *,
    state: Any,
    horizon_seconds: int,
    direction: str,
    expected_return: float,
    lower_return: float,
    upper_return: float,
    path_shape: str,
) -> ForecastPathV2:
    """Build a level-aware phase sequence from persisted Technical Core state.

    The terminal forecast remains untouched. The expected *route* is derived from
    horizon-relevant ATR/support/resistance plus momentum dynamics such as RSI
    stretch and MACD histogram acceleration/cooling.
    """
    expected = float(expected_return)
    terminal_sign = 1 if expected > 0 else -1 if expected < 0 else _direction_sign(direction)
    trend_sign = _direction_sign(getattr(state, "trend_state", None))
    momentum_sign = _direction_sign(getattr(state, "momentum_state", None))
    structure_sign = _direction_sign(getattr(state, "structure_state", None))

    source_timeframe, snapshot = _pick_snapshot(state, int(horizon_seconds))
    if snapshot is None or source_timeframe is None:
        width = max(0.0, float(upper_return) - float(lower_return))
        scale = max(abs(expected), width / 2.0, 0.0005)
        signed_scale = (terminal_sign or 1) * scale
        if terminal_sign and momentum_sign and momentum_sign != terminal_sign:
            points = ((0.0, 0.0), (0.20, -0.20 * signed_scale), (0.43, 0.06 * signed_scale), (0.70, 0.55 * expected), (1.0, expected))
            rationale = "Momentum går mot terminalretningen: kort motbevegelse forventes før hovedretningen eventuelt tar over."
            phases = ("MOTBEVEGELSE", "RETEST", "HOVEDRETNING")
        else:
            points = ((0.0, 0.0), (0.22, 0.18 * expected), (0.48, 0.43 * expected), (0.74, 0.69 * expected), (1.0, expected))
            rationale = "Ingen horizon-relevant nivåsnapshot var tilgjengelig; banen følger terminalsignalet konservativt."
            phases = ("DRIFT", "FORTSETTELSE")
        return ForecastPathV2(points=points, rationale=rationale, phases=phases)

    low, high = _level_aware_range(
        snapshot=snapshot,
        source_timeframe=source_timeframe,
        horizon_seconds=int(horizon_seconds),
        expected_return=expected,
        lower_return=float(lower_return),
        upper_return=float(upper_return),
    )
    dynamic_sign, exhaustion, dynamic_evidence = _momentum_dynamics(snapshot)

    normalized_shape = str(path_shape or "").upper()
    momentum_conflicts = bool(terminal_sign and momentum_sign and momentum_sign != terminal_sign)
    trend_conflicts = bool(terminal_sign and trend_sign and trend_sign != terminal_sign)
    structure_conflicts = bool(terminal_sign and structure_sign and structure_sign != terminal_sign)

    # Exhaustion has priority over the coarse terminal classification: a stretched
    # move that is visibly cooling is expected to complete a final push before the
    # retrace, not reverse instantaneously.
    if exhaustion and dynamic_sign > 0:
        points = (
            (0.0, 0.0),
            (0.18, 0.52 * high),
            (0.34, 0.78 * high),
            (0.66, 0.58 * low),
            (1.0, expected),
        )
        rationale = (
            f"{source_timeframe}: {dynamic_evidence}. Forventer siste bullish push mot lokal motstand, "
            f"deretter momentum-exhaustion og retrace mot ca. {0.58 * low * 100:+.2f}%, før terminal {expected * 100:+.2f}%."
        )
        phases = ("SISTE PUSH OPP", "EXHAUSTION", "RETRACE", "NY BALANSE")
    elif exhaustion and dynamic_sign < 0:
        points = (
            (0.0, 0.0),
            (0.18, 0.52 * low),
            (0.34, 0.78 * low),
            (0.66, 0.58 * high),
            (1.0, expected),
        )
        rationale = (
            f"{source_timeframe}: {dynamic_evidence}. Forventer siste bearish push mot støtte, "
            f"deretter exhaustion og rebound mot ca. {0.58 * high * 100:+.2f}%, før terminal {expected * 100:+.2f}%."
        )
        phases = ("SISTE PUSH NED", "EXHAUSTION", "REBOUND", "NY BALANSE")
    elif normalized_shape == "MEAN_REVERTING_OR_RANGE":
        first_sign = dynamic_sign or momentum_sign or trend_sign or structure_sign or (-terminal_sign if terminal_sign else 1)
        if first_sign < 0:
            first = 0.72 * low
            opposite = 0.58 * high
            phases = ("TEST NED", "MEAN REVERSION", "TEST OPP", "BALANSE")
        else:
            first = 0.72 * high
            opposite = 0.58 * low
            phases = ("TEST OPP", "MEAN REVERSION", "TEST NED", "BALANSE")
        points = ((0.0, 0.0), (0.22, first), (0.48, 0.16 * expected), (0.74, opposite), (1.0, expected))
        rationale = (
            f"{source_timeframe}-nivåer og ATR tilsier range/mean-reversion: forventet arbeidsområde "
            f"ca. {low * 100:+.2f}% til {high * 100:+.2f}% før terminal {expected * 100:+.2f}%."
        )
    elif momentum_conflicts:
        counter = 0.62 * (low if terminal_sign > 0 else high)
        continuation = 0.64 * (high if terminal_sign > 0 else low)
        points = ((0.0, 0.0), (0.20, counter), (0.44, 0.08 * expected), (0.72, continuation), (1.0, expected))
        rationale = (
            f"Momentum går mot terminalretningen; {source_timeframe}-ATR/nivåer peker mot retest rundt "
            f"{counter * 100:+.2f}% før eventuell fortsettelse mot {expected * 100:+.2f}%."
        )
        phases = ("MOTBEVEGELSE", "RETEST", "FORTSETTELSE")
    elif trend_conflicts or structure_conflicts:
        early = 0.28 * (high if terminal_sign > 0 else low)
        retest = 0.38 * (low if terminal_sign > 0 else high)
        points = ((0.0, 0.0), (0.22, early), (0.48, retest), (0.74, 0.62 * expected), (1.0, expected))
        rationale = f"Trend/struktur er ikke fullt bekreftet; {source_timeframe}-nivåene tilsier fremdrift, retest og først deretter terminalmove."
        phases = ("FREMDRIFT", "RETEST", "AVGJØRELSE")
    else:
        intermediate = high if terminal_sign > 0 else low
        points = (
            (0.0, 0.0),
            (0.20, 0.22 * expected),
            (0.46, 0.50 * expected),
            (0.73, _clamp(0.78 * expected, min(0.0, intermediate), max(0.0, intermediate))),
            (1.0, expected),
        )
        rationale = f"Trend, momentum og struktur støtter terminalretningen; {source_timeframe}-ATR/nivåer gir en relativt jevn fortsettelsesbane."
        phases = ("DRIFT", "FORTSETTELSE")

    return ForecastPathV2(
        points=tuple((float(p), float(value)) for p, value in points),
        rationale=rationale,
        phases=phases,
        source_timeframe=source_timeframe,
        expected_low_return=float(low),
        expected_high_return=float(high),
    )
