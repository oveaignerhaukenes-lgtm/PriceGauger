"""Causal, account-isolated NAV and V3 strategy timeline.

Both series use the timestamp stored with each Saxo account snapshot.
Strategy changes are observed, not given fabricated exact switch times.
No SQL, HTTP or trading authority; safe to import in a Streamlit chart.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
import json
from math import isfinite
from typing import Mapping, Sequence

from autotrader_saxo_account_truth_v1 import COLLECTION_SECONDS

MAX_GAP_SECONDS = int(COLLECTION_SECONDS * 2.5)


@dataclass(frozen=True, slots=True)
class ObservedStrategyPeriodV1:
    first_observed: datetime
    last_observed: datetime
    strategy_key: str
    timeframe: str
    market: str
    instance_id: str
    live_armed: bool
    label: str
    observations: int


def _time(raw) -> datetime:
    when = raw if isinstance(raw, datetime) else datetime.fromisoformat(
        str(raw).replace("Z", "+00:00")
    )
    if when.tzinfo is None:
        raise ValueError("account chart requires timezone-aware Saxo timestamps")
    return when.astimezone(timezone.utc)


def _context(snapshot: Mapping) -> tuple[str, str, str, str, bool, str]:
    """Do not assign a strategy unless one unambiguous active V3 owner exists."""
    try:
        contexts = json.loads(str(snapshot.get("context_json") or "[]"))
    except (TypeError, ValueError):
        contexts = []
    if not isinstance(contexts, list):
        contexts = []
    valid = [v for v in contexts if isinstance(v, dict)]
    armed = [v for v in valid if v.get("live_armed") is True]
    if len(armed) == 1:
        value = armed[0]
        strategy = str(value.get("strategy") or "").strip()
        if not strategy or not str(value.get("instance_id") or "").strip():
            return ("","","","",False,"Strategi ukjent")
        timeframe = str(value.get("timeframe") or "").strip()
        market = str(value.get("market") or "").strip()
        owner = str(value.get("instance_id") or "").strip()
        name = f"{strategy} · {timeframe}" if timeframe else strategy
        return (strategy, timeframe, market, owner, True, name)
    if len(armed) > 1:
        return ("","","","",False,"Flere LIVE-instanser · ukjent")
    if len(valid) == 1:
        value = valid[0]
        strategy = str(value.get("strategy") or "").strip()
        if not strategy:
            return ("","","","",False,"Ingen LIVE-strategi")
        return (strategy, str(value.get("timeframe") or ""),
                str(value.get("market") or ""),
                str(value.get("instance_id") or ""), False,
                f"AV · {strategy}")
    return ("","","","",False,"Ingen registrert LIVE-strategi")


def strategy_periods_from_snapshots_v1(
    samples: Sequence[Mapping],
    *,
    max_gap_seconds: int = MAX_GAP_SECONDS,
) -> tuple[ObservedStrategyPeriodV1, ...]:
    """Merge only consecutive matching snapshots, never bridge missing time.

    Start/end describe the FIRST/LAST OBSERVED snapshots in the segment.
    They are not broker-confirmed exact moments of a configuration switch.
    """
    if max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be positive")
    if not samples:
        return ()
    ordered = sorted(samples, key=lambda r: _time(r["observed_at"]))
    identities = {
        (str(r["account_id"]), str(r["currency"])) for r in ordered
    }
    if len(identities) != 1:
        raise ValueError("account strategy timeline cannot mix Saxo account/currency")
    result: list[ObservedStrategyPeriodV1] = []
    prev_when: datetime | None = None
    prev_key: tuple | None = None
    for item in ordered:
        when = _time(item["observed_at"])
        strategy, timeframe, market, instance, live, label = _context(item)
        key = (strategy, timeframe, market, instance, live, label)
        gap = (
            prev_when is not None
            and (when - prev_when).total_seconds() > max_gap_seconds
        )
        if result and key == prev_key and not gap and when > prev_when:
            previous = result[-1]
            result[-1] = ObservedStrategyPeriodV1(
                first_observed=previous.first_observed,
                last_observed=when,
                strategy_key=strategy,
                timeframe=timeframe,
                market=market,
                instance_id=instance,
                live_armed=live,
                label=label,
                observations=previous.observations + 1,
            )
        elif prev_when is None or when > prev_when:
            result.append(ObservedStrategyPeriodV1(
                first_observed=when, last_observed=when, strategy_key=strategy,
                timeframe=timeframe, market=market, instance_id=instance,
                live_armed=live, label=label, observations=1,
            ))
        prev_when, prev_key = when, key
    return tuple(result)


def build_saxo_account_strategy_chart_v1(
    samples: Sequence[Mapping], *, height: int = 320,
):
    """Plot Saxo TotalValue and observed strategy segments on a shared UTC axis.

    Never interpolate across > 2.5 sample intervals, and never connect broker
    values with CalculationReliability!=Ok or missing/nonfinite TotalValue.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from plotly.colors import qualitative

    periods = strategy_periods_from_snapshots_v1(samples)
    if not samples:
        raise ValueError("account chart needs at least one observed sample")
    ordered = sorted(samples, key=lambda r: _time(r["observed_at"]))
    currency = str(ordered[0]["currency"])
    xs: list[datetime | None] = []
    ys: list[float | None] = []
    previous_at: datetime | None = None
    valid_count = 0
    for sample in ordered:
        observed = _time(sample["observed_at"])
        if previous_at is not None and (observed - previous_at).total_seconds() > MAX_GAP_SECONDS:
            xs.append(None)
            ys.append(None)
        reliable = str(sample.get("calculation_reliability") or "").lower() == "ok"
        try:
            value = float(sample["total_value"])
            reliable = reliable and isfinite(value)
        except (ValueError, TypeError, KeyError):
            reliable = False
            value = 0.0
        xs.append(observed)
        ys.append(value if reliable else None)
        valid_count += int(reliable)
        previous_at = observed

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.035,
        row_heights=[0.8, 0.2],
    )
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        name="Saxo TotalValue", connectgaps=False,
        line=dict(width=2.4, color="#3286D1"),
        marker=dict(size=4),
        hovertemplate=f"%{{x|%d.%m.%Y %H:%M}} UTC"
                      f"<extra>Saxo TotalValue ({escape(currency)})</extra>"
                      f"<br>Kontoverdi: %{{y:,.2f}} {escape(currency)}",
    ), row=1, col=1)

    colors = qualitative.Safe + qualitative.Plotly
    active_keys = sorted({p.strategy_key for p in periods if p.live_armed})
    colors_by_key = {k: colors[i % len(colors)] for i, k in enumerate(active_keys)}
    date_extent = (periods[-1].last_observed - periods[0].first_observed).total_seconds()
    annotation_min = max(15 * 60, date_extent * 0.08)
    for p in periods:
        colored = colors_by_key.get(p.strategy_key, "#9199A4") if p.live_armed else "#9199A4"
        # Plot EXACTLY the range of observations. Do not fill to the next
        # first-seen strategy or imply knowledge after the last snapshot.
        first, last = p.first_observed, p.last_observed
        label = escape(p.label)
        period_info = (
            f"{label}<br>Først observert: {first:%d.%m %H:%M} UTC"
            f"<br>Sist observert: {last:%d.%m %H:%M} UTC"
            f"<br>Observasjoner: {p.observations}"
            f"<br>Marked: {escape(p.market or 'Ukjent')}"
            "<br><i>Byttetidspunkt er ikke verifisert</i>"
        )
        if first == last:
            fig.add_trace(go.Scatter(
                x=[first], y=[0], mode="markers", showlegend=False,
                marker=dict(color=colored, size=11, symbol="square"),
                hovertemplate=period_info+"<extra></extra>",
            ), row=2, col=1)
        else:
            fig.add_trace(go.Scatter(
                x=[first,last], y=[0,0], mode="lines", showlegend=False,
                line=dict(color=colored, width=18),
                hovertemplate=period_info+"<extra></extra>",
            ), row=2, col=1)
            if (last-first).total_seconds() >= annotation_min:
                mid = first + (last-first)/2
                # Label the strategy IN the time band directly below NAV.
                # Short segments stay readable via hover instead of overlap.
                fig.add_annotation(
                    x=mid, y=0, xref="x2", yref="y2",
                    text=escape(p.label[:32]), showarrow=False,
                    font=dict(size=10, color="#1D2733"),
                    bgcolor="rgba(255,255,255,0.85)", borderpad=2,
                )

    fig.update_xaxes(showgrid=True, gridcolor="rgba(120,130,140,.10)", row=1, col=1)
    fig.update_xaxes(
        title_text="Tid (UTC) · strategi observert", tickformat="%d.%m %H:%M",
        showgrid=True, row=2, col=1,
    )
    fig.update_yaxes(title_text=f"Kontoverdi ({currency})", row=1, col=1)
    fig.update_yaxes(
        range=[-0.7,0.7], visible=False, fixedrange=True, row=2, col=1,
    )
    fig.update_layout(
        height=height, margin=dict(l=6,r=10,t=10,b=50),
        showlegend=False, hovermode="closest", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig, valid_count, periods


__all__ = [
    "ObservedStrategyPeriodV1", "strategy_periods_from_snapshots_v1",
    "build_saxo_account_strategy_chart_v1", "MAX_GAP_SECONDS",
]
