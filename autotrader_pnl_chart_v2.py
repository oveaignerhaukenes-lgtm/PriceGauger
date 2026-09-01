from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_strategy_catalog_v2 import strategy_spec_v2


PAPER_COLORS = ("#2563eb", "#7c3aed", "#059669")


def _strategy_label(strategy_key: str) -> str:
    try:
        return strategy_spec_v2(strategy_key).label
    except Exception:
        return str(strategy_key)


def build_automanager_pnl_figure_v2(comparison: AutoManagerPnlComparisonV2) -> go.Figure:
    """One durable product-history figure with linked LIVE and paper timelines."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        row_heights=[0.38, 0.62],
        subplot_titles=("Faktisk LIVE · realisert og avstemt Saxo-P/L", "Modeller · canonical 30m paper-replay"),
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

    for index, series in enumerate(comparison.paper_series):
        spec = strategy_spec_v2(series.strategy_key)
        points = series.points
        fig.add_trace(
            go.Scatter(
                x=[item.closed_at for item in points],
                y=[((item.equity / series.seed_equity) - 1.0) * 100.0 for item in points],
                customdata=[item.position_state for item in points],
                mode="lines",
                name=f"Paper · {spec.label}",
                line={"color": PAPER_COLORS[index % len(PAPER_COLORS)], "width": 2.0},
                hovertemplate=(
                    f"{spec.label}<br>%{{x|%d.%m.%Y %H:%M:%S}} norsk tid<br>"
                    "%{y:+.2f}%<br>tilstand %{customdata}<extra></extra>"
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
