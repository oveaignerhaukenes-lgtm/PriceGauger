from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Iterable

from analyst_companion_v2 import CompanionAnalysisV2, TechnicalScenarioV2


def _utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _points(points: Iterable[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _scenario_price_points(scenario: TechnicalScenarioV2, reference_price: float) -> list[tuple[float, float]]:
    return [
        (42.0 + 55.0 * float(progress), reference_price * (1.0 + float(value)))
        for progress, value in scenario.path_profile
    ]


def render_ta_scenario_chart_v2(view, analysis: CompanionAnalysisV2) -> str:
    """Render AI TA scenarios without allowing the model to draw arbitrary SVG.

    The model supplies only validated cumulative-return path points. This renderer
    deterministically maps them onto the observed price scale.
    """
    scenarios = tuple(analysis.scenarios)
    history_raw = tuple(getattr(view, "price_history", ()) or ())[-60:]
    parsed_history: list[tuple[datetime, float]] = []
    for stamp, price in history_raw:
        parsed = _utc(stamp)
        if parsed is not None:
            parsed_history.append((parsed, float(price)))
    parsed_history.sort(key=lambda item: item[0])
    if not parsed_history or not scenarios:
        return ""

    reference_price = parsed_history[-1][1]
    scenario_points = [_scenario_price_points(scenario, reference_price) for scenario in scenarios]
    interval_prices: list[float] = []
    for scenario in scenarios:
        interval_prices.extend(
            [
                reference_price * (1.0 + float(scenario.lower_return)),
                reference_price * (1.0 + float(scenario.upper_return)),
            ]
        )
    prices = [price for _, price in parsed_history]
    for points in scenario_points:
        prices.extend(price for _, price in points)
    prices.extend(interval_prices)
    low = min(prices)
    high = max(prices)
    span = max(high - low, abs(reference_price) * 0.001, 0.01)
    low -= span * 0.10
    high += span * 0.10

    def ymap(price: float) -> float:
        return 92.0 - (float(price) - low) / (high - low) * 80.0

    first = parsed_history[0][0]
    last = parsed_history[-1][0]
    duration = max(1.0, (last - first).total_seconds())
    history_xy = [
        (2.0 + 37.0 * (stamp - first).total_seconds() / duration, ymap(price))
        for stamp, price in parsed_history
    ]

    fan_parts: list[str] = []
    path_parts: list[str] = []
    for index, (scenario, raw_points) in enumerate(zip(scenarios, scenario_points)):
        rank = index + 1
        opacity = max(0.34, min(0.92, 0.28 + float(scenario.probability) * 0.95))
        width = 1.15 + float(scenario.probability) * 1.4
        dash = "" if index == 0 else "stroke-dasharray:2 1.5;"
        terminal_x = 97.0
        terminal_low = ymap(reference_price * (1.0 + scenario.lower_return))
        terminal_high = ymap(reference_price * (1.0 + scenario.upper_return))
        # Narrow near T0 and widen toward each scenario's terminal uncertainty.
        fan_points = _points(
            (
                (42.0, ymap(reference_price)),
                (terminal_x, terminal_high),
                (terminal_x, terminal_low),
            )
        )
        fan_parts.append(
            f'<polygon class="pg-ta-scenario-fan" style="fill-opacity:{0.025 + scenario.probability * 0.10:.3f}" points="{fan_points}" />'
        )
        xy = [(x, ymap(price)) for x, price in raw_points]
        path_parts.append(
            f'<polyline class="pg-ta-scenario-path" style="stroke-opacity:{opacity:.3f};stroke-width:{width:.2f};{dash}" '
            f'points="{_points(xy)}"><title>{html.escape(scenario.label)} · {scenario.probability:.0%}</title></polyline>'
        )

    legend = " · ".join(
        f"{html.escape(scenario.label)} {scenario.probability:.0%}"
        for scenario in scenarios
    )
    return (
        '<div class="pg-ta-scenario-chart">'
        '<div class="pg-ta-scenario-head"><span>TA ANALYST · SCENARIER</span>'
        f'<span>{html.escape(str(view.horizon_seconds // 60))}m horizon</span></div>'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" '
        'aria-label="AI technical scenario distribution from supplied Technical Core data">'
        '<line class="pg-ta-scenario-now" x1="40" x2="40" y1="7" y2="95" />'
        f'{"".join(fan_parts)}'
        f'<polyline class="pg-ta-scenario-history" points="{_points(history_xy)}" />'
        f'{"".join(path_parts)}'
        '</svg>'
        f'<div class="pg-ta-scenario-legend">{legend}</div>'
        '</div>'
    )


TA_SCENARIO_CSS = """
<style>
.pg-ta-scenario-chart{border:1px solid rgba(128,128,128,.22);border-radius:.65rem;padding:.6rem .7rem;margin:.65rem 0;background:rgba(128,128,128,.02)}
.pg-ta-scenario-head{display:flex;justify-content:space-between;font-size:.64rem;font-weight:760;letter-spacing:.045em;opacity:.72}
.pg-ta-scenario-chart svg{display:block;width:100%;height:12rem;margin:.1rem 0}
.pg-ta-scenario-now{stroke:rgba(100,116,139,.66);stroke-width:.8;stroke-dasharray:2 1.5;vector-effect:non-scaling-stroke}
.pg-ta-scenario-history{fill:none;stroke:currentColor;stroke-width:1.35;vector-effect:non-scaling-stroke}
.pg-ta-scenario-fan{fill:var(--primary-color,#4f6f9f);stroke:none}
.pg-ta-scenario-path{fill:none;stroke:var(--primary-color,#355f91);vector-effect:non-scaling-stroke}
.pg-ta-scenario-legend{font-size:.61rem;line-height:1.35;opacity:.68}
</style>
"""
