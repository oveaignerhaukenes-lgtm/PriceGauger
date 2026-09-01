from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from autotrader_pnl_comparison_v2 import AutoManagerPnlComparisonV2
from autotrader_strategy_catalog_v2 import strategy_spec_v2


PAPER_COLORS = ("#2563eb", "#7c3aed", "#059669")


def build_automanager_pnl_figure_v2(comparison: AutoManagerPnlComparisonV2) -> go.Figure:
    """One shared-time figure with semantically separate LIVE and paper panels."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        row_heights=[0.38, 0.62],
        subplot_titles=("Faktisk LIVE · realisert og avstemt Saxo-P/L", "Modeller · canonical 30m paper-replay"),
    )
    live = comparison.live_realized
    fig.add_trace(
        go.Scatter(
            x=[item.occurred_at for item in live],
            y=[item.return_pct for item in live],
            customdata=[item.cumulative_pnl for item in live],
            mode="lines+markers",
            name="LIVE · realisert Saxo",
            line={"color": "#dc2626", "width": 2.4, "shape": "hv"},
            marker={"size": 5},
            hovertemplate=(
                "LIVE realisert<br>%{x|%d.%m %H:%M} UTC<br>"
                "%{y:+.2f}% av startkapital<br>%{customdata:+.2f} "
                f"{comparison.currency}<extra></extra>"
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
                    f"{spec.label}<br>%{{x|%d.%m %H:%M}} UTC<br>"
                    "%{y:+.2f}%<br>tilstand %{customdata}<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

    for row in (1, 2):
        fig.add_hline(y=0.0, line_width=0.8, line_dash="dot", line_color="rgba(17,24,39,0.45)", row=row, col=1)
        fig.update_yaxes(title_text="P/L · % av startkapital", ticksuffix="%", row=row, col=1)
    fig.update_xaxes(title_text="Tid", row=2, col=1)
    fig.update_layout(
        template="plotly_white",
        height=610,
        margin={"l": 70, "r": 35, "t": 105, "b": 45},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.07, "xanchor": "left", "x": 0},
        hovermode="x unified",
        uirevision=f"AutoManagerPnl:{comparison.pilot_key}:{comparison.started_at.isoformat()}",
    )
    return fig


__all__ = ["build_automanager_pnl_figure_v2"]