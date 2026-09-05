from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from autotrader_macd_timeframe_controls_v1 import (
    MACD_CONTROL_STRATEGY_KEYS_V1,
    macd_control_strategy_label_v1,
)
from autotrader_pnl_comparison_v2 import (
    PAPER_SCALE_PILOT_EQUIVALENT,
    AutoManagerPnlComparisonV2,
)
from autotrader_shadow_leverage_v2 import (
    apply_schedule_to_series_v2,
    load_live_leverage_schedule_v2,
)
from autotrader_strategy_catalog_v2 import strategy_display_label_v2
from autotrader_strong_cocktail_shadow_v2 import (
    MACD_1M_CONTROL_STRATEGY_KEY,
    STRONG_COCKTAIL_STRATEGY_KEY,
)
from spring_trade_engine.persistence import load_spring_observations_v1


PAPER_COLORS = (
    "#2563eb",
    "#7c3aed",
    "#059669",
    "#d97706",
    "#0891b2",
    "#be123c",
    "#4f46e5",
    "#0f766e",
    "#a16207",
    "#9333ea",
    "#0369a1",
    "#b91c1c",
)
_MACD_CONTROL_MINUTES_BY_KEY = {
    key: minutes for minutes, key in MACD_CONTROL_STRATEGY_KEYS_V1.items()
}


def _strategy_label(strategy_key: str) -> str:
    key = str(strategy_key)
    if key == STRONG_COCKTAIL_STRATEGY_KEY:
        return "Strong Cocktail · 1m event + MTF context"
    if key == MACD_1M_CONTROL_STRATEGY_KEY:
        return "1m MACD flip · control"
    minutes = _MACD_CONTROL_MINUTES_BY_KEY.get(key)
    if minutes is not None:
        return macd_control_strategy_label_v1(minutes)
    return strategy_display_label_v2(key)


def _leverage_schedule(comparison: AutoManagerPnlComparisonV2):
    account_id, raw_uic, asset_type, _instrument_id = comparison.product_key.split(":", 3)
    return load_live_leverage_schedule_v2(
        pilot_key=comparison.pilot_key,
        account_id=account_id,
        uic=int(raw_uic),
        asset_type=asset_type,
    )


def _models_for_chart(comparison: AutoManagerPnlComparisonV2):
    """Return model series in pilot-equivalent scale exactly once.

    Persisted Strategy Series already store pilot-equivalent equity. Legacy or
    synthetic callers may still supply raw 1x series, in which case the chart retains
    the compatibility transformation. Persisted UI data must never receive leverage
    a second time.
    """
    if comparison.paper_scale == PAPER_SCALE_PILOT_EQUIVALENT:
        try:
            return comparison.paper_series, _leverage_schedule(comparison), True
        except Exception:
            return comparison.paper_series, None, True
    try:
        schedule = _leverage_schedule(comparison)
        return apply_schedule_to_series_v2(comparison.paper_series, schedule=schedule), schedule, False
    except Exception:
        return comparison.paper_series, None, False


def _spring_points_for_chart(comparison: AutoManagerPnlComparisonV2):
    """Read Spring's persisted blind observations without making them a strategy."""
    try:
        _account_id, _raw_uic, _asset_type, raw_instrument_id = comparison.product_key.split(":", 3)
        return load_spring_observations_v1(
            instrument_id=int(raw_instrument_id),
            start=comparison.started_at,
            end=comparison.as_of,
            limit=10000,
        )
    except Exception:
        return ()


def build_automanager_pnl_figure_v2(comparison: AutoManagerPnlComparisonV2) -> go.Figure:
    """One durable product-history figure with LIVE, model and Spring timelines."""
    model_series, leverage_schedule, persisted_pilot_scale = _models_for_chart(comparison)
    spring_points = _spring_points_for_chart(comparison)
    if leverage_schedule is None:
        model_title = "Modeller · pilot-ekvivalent" if persisted_pilot_scale else "Modeller · 1×"
    else:
        model_title = f"Modeller · ca. {leverage_schedule.representative_leverage:.1f}×"

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.24, 0.48, 0.28],
        specs=[[{}], [{}], [{"secondary_y": True}]],
        subplot_titles=(
            "LIVE · realisert P/L",
            model_title,
            "Spring · blind observasjon",
        ),
    )
    live = comparison.live_realized
    live_custom = [
        [item.cumulative_pnl, _strategy_label(item.strategy_key)]
        for item in live
    ]
    fig.add_trace(
        go.Scatter(
            x=[item.occurred_at for item in live],
            y=[item.return_pct for item in live],
            customdata=live_custom,
            mode="lines+markers",
            name="LIVE · realisert Saxo",
            line={"color": "#dc2626", "width": 1.5, "shape": "hv"},
            marker={"size": 4},
            hovertemplate=(
                "LIVE · %{x|%H:%M}<br>%{y:+.2f}% · %{customdata[0]:+.2f} "
                f"{comparison.currency}<br>%{{customdata[1]}}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    for index, series in enumerate(model_series):
        label = _strategy_label(series.strategy_key)
        points = series.points
        mode = str(series.execution_mode).upper()
        is_adaptive = mode == "SHADOW_ADAPTIVE"
        is_control = mode == "SHADOW_CONTROL"
        prefix = "Shadow" if is_adaptive else ("Control" if is_control else "Paper")
        dash = "solid" if is_adaptive else ("dash" if is_control else "dot")
        width = 1.5 if is_adaptive else (1.3 if is_control else 1.1)
        fig.add_trace(
            go.Scatter(
                x=[item.closed_at for item in points],
                y=[((item.equity / series.seed_equity) - 1.0) * 100.0 for item in points],
                customdata=[item.position_state for item in points],
                mode="lines",
                name=f"{prefix} · {label}",
                line={
                    "color": PAPER_COLORS[index % len(PAPER_COLORS)],
                    "width": width,
                    "dash": dash,
                },
                hovertemplate=(
                    f"{label} · %{{x|%H:%M}}<br>"
                    "%{y:+.2f}% · %{customdata}<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

    if spring_points:
        fig.add_trace(
            go.Scatter(
                x=[item.observed_at for item in spring_points],
                y=[item.displacement_pct for item in spring_points],
                customdata=[
                    [
                        item.turning_state,
                        item.shock_score,
                        item.energy_proxy,
                        item.velocity_pct_per_min,
                    ]
                    for item in spring_points
                ],
                mode="lines",
                name="Spring · displacement fra 0",
                line={"color": "#111827", "width": 1.3},
                hovertemplate=(
                    "Spring · %{x|%H:%M}<br>"
                    "Δeq %{y:+.3f}% · %{customdata[0]}<br>"
                    "shock z %{customdata[1]:.2f} · energy %{customdata[2]:.2f}<br>"
                    "velocity %{customdata[3]:+.3f}%/min<extra></extra>"
                ),
            ),
            row=3,
            col=1,
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=[item.observed_at for item in spring_points],
                y=[item.shock_score for item in spring_points],
                mode="lines",
                name="Spring · shock z",
                line={"color": "#9ca3af", "width": 0.9, "dash": "dot"},
                hovertemplate="Spring shock · %{x|%H:%M}<br>z %{y:.2f}<extra></extra>",
            ),
            row=3,
            col=1,
            secondary_y=True,
        )
        fig.add_trace(
            go.Scatter(
                x=[item.observed_at for item in spring_points],
                y=[item.energy_proxy for item in spring_points],
                mode="lines",
                name="Spring · energy proxy",
                visible="legendonly",
                line={"color": "#6b7280", "width": 0.8, "dash": "dash"},
                hovertemplate="Spring energy · %{x|%H:%M}<br>%{y:.2f}<extra></extra>",
            ),
            row=3,
            col=1,
            secondary_y=True,
        )
        turning_points = tuple(
            item for item in spring_points if item.turning_state in {"TURN_UP", "TURN_DOWN"}
        )
        if turning_points:
            fig.add_trace(
                go.Scatter(
                    x=[item.observed_at for item in turning_points],
                    y=[item.displacement_pct for item in turning_points],
                    customdata=[
                        [item.turning_state, item.shock_score, item.energy_proxy]
                        for item in turning_points
                    ],
                    mode="markers",
                    name="Spring · vending",
                    marker={
                        "size": 8,
                        "symbol": [
                            "triangle-up" if item.turning_state == "TURN_UP" else "triangle-down"
                            for item in turning_points
                        ],
                        "color": "#111827",
                    },
                    hovertemplate=(
                        "%{customdata[0]} · %{x|%H:%M}<br>"
                        "Δeq %{y:+.3f}% · shock %{customdata[1]:.2f} · energy %{customdata[2]:.2f}"
                        "<extra></extra>"
                    ),
                ),
                row=3,
                col=1,
                secondary_y=False,
            )

    # Strategy switches remain visible as thin boundaries. Their long labels were
    # intentionally removed from the plotting surface; the strategy itself is already
    # visible in the legend and activity log, and overlapping annotations obscured data.
    for epoch in comparison.live_epochs:
        fig.add_shape(
            type="line",
            x0=epoch.started_at,
            x1=epoch.started_at,
            y0=0.0,
            y1=1.0,
            xref="x",
            yref="paper",
            line={"width": 0.8, "dash": "dot", "color": "rgba(17,24,39,0.32)"},
        )

    for row in (1, 2):
        fig.add_hline(y=0.0, line_width=0.7, line_dash="dot", line_color="rgba(17,24,39,0.38)", row=row, col=1)
        fig.update_yaxes(title_text="P/L · %", ticksuffix="%", row=row, col=1)
    fig.add_hline(y=0.0, line_width=0.8, line_dash="dot", line_color="rgba(17,24,39,0.45)", row=3, col=1)
    fig.update_yaxes(title_text="Δ eq · %", ticksuffix="%", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="shock / energy", row=3, col=1, secondary_y=True)

    range_buttons = [
        {"count": 1, "label": "1t", "step": "hour", "stepmode": "backward"},
        {"count": 4, "label": "4t", "step": "hour", "stepmode": "backward"},
        {"count": 12, "label": "12t", "step": "hour", "stepmode": "backward"},
        {"count": 1, "label": "1d", "step": "day", "stepmode": "backward"},
        {"count": 3, "label": "3d", "step": "day", "stepmode": "backward"},
        {"label": "Alt", "step": "all"},
    ]
    fig.update_xaxes(
        tickformat="%H:%M",
        hoverformat="%H:%M",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
    )
    fig.update_xaxes(title_text="Tid", row=3, col=1)
    fig.update_xaxes(
        rangeselector={"buttons": range_buttons, "x": 0.0, "xanchor": "left", "y": -0.14, "yanchor": "top"},
        rangeslider={"visible": True, "thickness": 0.07},
        row=3,
        col=1,
    )
    fig.update_layout(
        template="plotly_white",
        height=840,
        margin={"l": 58, "r": 235, "t": 68, "b": 88},
        legend={
            "orientation": "v",
            "yanchor": "top",
            "y": 1.0,
            "xanchor": "left",
            "x": 1.01,
            "font": {"size": 11},
            "title": {"text": "Legend · hover / scroll"},
            "maxheight": 0.52,
        },
        hovermode="closest",
        dragmode="pan",
        uirevision=f"AutoManagerPnlProduct:{comparison.product_key}:{comparison.started_at.isoformat()}",
    )
    return fig


__all__ = ["build_automanager_pnl_figure_v2"]
