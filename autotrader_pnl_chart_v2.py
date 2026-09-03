from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_shadow_leverage_v2 import (
    apply_schedule_to_series_v2,
    load_live_leverage_schedule_v2,
)
from autotrader_strategy_catalog_v2 import strategy_display_label_v2
from autotrader_strong_cocktail_shadow_v2 import (
    MACD_1M_CONTROL_STRATEGY_KEY,
    STRONG_COCKTAIL_STRATEGY_KEY,
)


PAPER_COLORS = ("#2563eb", "#7c3aed", "#059669", "#d97706", "#0891b2", "#be123c")


def _strategy_label(strategy_key: str) -> str:
    key = str(strategy_key)
    if key == STRONG_COCKTAIL_STRATEGY_KEY:
        return "Strong Cocktail · 1m event + MTF context"
    if key == MACD_1M_CONTROL_STRATEGY_KEY:
        return "1m MACD flip · control"
    return strategy_display_label_v2(key)


def _pilot_equivalent_models(comparison: AutoManagerPnlComparisonV2):
    """Return model series scaled to the product's proven LIVE economic exposure.

    ``product_key`` is the canonical account/UIC/AssetType/instrument identity emitted
    by the comparison loader. Tests and legacy callers that supply a synthetic key
    simply retain 1x model curves rather than failing chart rendering.
    """
    try:
        account_id, raw_uic, asset_type, _instrument_id = comparison.product_key.split(":", 3)
        schedule = load_live_leverage_schedule_v2(
            pilot_key=comparison.pilot_key,
            account_id=account_id,
            uic=int(raw_uic),
            asset_type=asset_type,
        )
        scaled = apply_schedule_to_series_v2(comparison.paper_series, schedule=schedule)
        return scaled, schedule
    except Exception:
        return comparison.paper_series, None


def build_automanager_pnl_figure_v2(comparison: AutoManagerPnlComparisonV2) -> go.Figure:
    """One durable product-history figure with linked LIVE and model timelines."""
    model_series, leverage_schedule = _pilot_equivalent_models(comparison)
    if leverage_schedule is None:
        model_title = "Modeller · 1x signalavkastning"
    else:
        representative = leverage_schedule.representative_leverage
        model_title = f"Modeller · pilot-ekvivalent eksponering · ca. {representative:.1f}x"

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        row_heights=[0.38, 0.62],
        subplot_titles=(
            "Faktisk LIVE · realisert og avstemt Saxo-P/L",
            model_title,
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
            line={"color": "#dc2626", "width": 2.4, "shape": "hv"},
            marker={"size": 5},
            hovertemplate=(
                "LIVE realisert<br>%{x|%d.%m.%Y %H:%M:%S} norsk tid<br>"
                "%{y:+.2f}% av historisk startkapital<br>%{customdata[0]:+.2f} "
                f"{comparison.currency}<br>Strategi: %{{customdata[1]}}<extra></extra>"
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
        width = 2.6 if is_adaptive else (2.2 if is_control else 1.8)
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
                    f"{label}<br>%{{x|%d.%m.%Y %H:%M:%S}} norsk tid<br>"
                    "%{y:+.2f}% av pilotkapital<br>tilstand %{customdata}<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

    # Strategy pilots remain separate audit cohorts, but their boundaries are shown
    # on one product timeline so the user can correlate each epoch with TradingView.
    for epoch in comparison.live_epochs:
        label = _strategy_label(epoch.strategy_key)
        fig.add_shape(
            type="line",
            x0=epoch.started_at,
            x1=epoch.started_at,
            y0=0.0,
            y1=1.0,
            xref="x",
            yref="paper",
            line={"width": 1.0, "dash": "dot", "color": "rgba(17,24,39,0.40)"},
        )
        fig.add_annotation(
            x=epoch.started_at,
            y=1.015,
            xref="x",
            yref="paper",
            text=label,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font={"size": 10},
            textangle=-18,
        )

    for row in (1, 2):
        fig.add_hline(y=0.0, line_width=0.8, line_dash="dot", line_color="rgba(17,24,39,0.45)", row=row, col=1)
        fig.update_yaxes(title_text="P/L · % av historisk startkapital", ticksuffix="%", row=row, col=1)

    range_buttons = [
        {"count": 1, "label": "1t", "step": "hour", "stepmode": "backward"},
        {"count": 4, "label": "4t", "step": "hour", "stepmode": "backward"},
        {"count": 12, "label": "12t", "step": "hour", "stepmode": "backward"},
        {"count": 1, "label": "1d", "step": "day", "stepmode": "backward"},
        {"count": 3, "label": "3d", "step": "day", "stepmode": "backward"},
        {"label": "Alt", "step": "all"},
    ]
    fig.update_xaxes(
        tickformat="%d.%m %H:%M",
        hoverformat="%d.%m.%Y %H:%M:%S",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
    )
    fig.update_xaxes(title_text="Tid · norsk tid", row=2, col=1)
    fig.update_xaxes(
        rangeselector={"buttons": range_buttons, "x": 0.0, "xanchor": "left", "y": -0.14, "yanchor": "top"},
        rangeslider={"visible": True, "thickness": 0.08},
        row=2,
        col=1,
    )
    fig.update_layout(
        template="plotly_white",
        height=690,
        margin={"l": 70, "r": 35, "t": 125, "b": 95},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.08, "xanchor": "left", "x": 0},
        hovermode="x unified",
        dragmode="zoom",
        uirevision=f"AutoManagerPnlProduct:{comparison.product_key}:{comparison.started_at.isoformat()}",
    )
    return fig


__all__ = ["build_automanager_pnl_figure_v2"]
