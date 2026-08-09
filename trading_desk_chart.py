from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading_desk import ChartBar, normalized_close_series


OVERLAY_NORMALIZED = "Normalisert (100)"
OVERLAY_ACTUAL = "Faktisk pris"


def overlay_axis_title(mode: str) -> str:
    if mode == OVERLAY_NORMALIZED:
        return "Overlay · indeks (100 = start)"
    if mode == OVERLAY_ACTUAL:
        return "Overlay · faktisk pris"
    raise ValueError(f"Unsupported TradingDesk overlay mode: {mode}")


def build_trading_desk_figure(
    *,
    market: str,
    timeframe: str,
    window_hours: int,
    primary: Sequence[ChartBar],
    overlays: Mapping[str, Sequence[ChartBar]],
    overlay_mode: str,
    empty_message: str = "Ingen ferdige canonical 1m-bars å vise ennå.",
) -> go.Figure:
    """Build the operational TradingDesk chart with explicit axis ownership.

    Primary-market candles use the right-hand price axis. Cross-market overlays
    use the separate left-hand axis. Volume has its own lower panel and right-hand
    axis. Keeping those responsibilities fixed makes multi-market charts readable
    without relying on trace colours alone.
    """

    overlay_title = overlay_axis_title(overlay_mode)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.78, 0.22],
        specs=[[{"secondary_y": True}], [{}]],
    )

    if primary:
        fig.add_trace(
            go.Candlestick(
                x=[item.bar_time for item in primary],
                open=[item.open for item in primary],
                high=[item.high for item in primary],
                low=[item.low for item in primary],
                close=[item.close for item in primary],
                name=f"{market} · candles",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )

        if overlay_mode == OVERLAY_NORMALIZED:
            indexed = normalized_close_series(primary)
            fig.add_trace(
                go.Scatter(
                    x=[stamp for stamp, _ in indexed],
                    y=[value for _, value in indexed],
                    mode="lines",
                    name=f"{market} · indeks",
                    hovertemplate=f"{market} indeks<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        fig.add_trace(
            go.Bar(
                x=[item.bar_time for item in primary],
                y=[item.volume for item in primary],
                name=f"{market} · volum",
                hovertemplate="Volum<br>%{x|%d.%m %H:%M} UTC<br>%{y}<extra></extra>",
            ),
            row=2,
            col=1,
        )

        last_close = float(primary[-1].close)
        fig.add_hline(
            y=last_close,
            line_width=1,
            line_dash="dot",
            annotation_text=f"Siste {last_close:g}",
            annotation_position="top right",
            row=1,
            col=1,
        )
    else:
        fig.add_annotation(
            text=empty_message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.58,
            showarrow=False,
        )

    for overlay_market, bars in overlays.items():
        if not bars:
            continue
        if overlay_mode == OVERLAY_NORMALIZED:
            points = normalized_close_series(bars)
        else:
            points = tuple((item.bar_time, item.close) for item in bars)

        fig.add_trace(
            go.Scatter(
                x=[stamp for stamp, _ in points],
                y=[value for _, value in points],
                mode="lines",
                name=overlay_market,
                hovertemplate=f"{overlay_market}<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.4g}}<extra></extra>",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    fig.update_yaxes(
        title_text=f"{market} · pris",
        side="right",
        showgrid=True,
        zeroline=False,
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text=overlay_title,
        side="left",
        showgrid=False,
        zeroline=False,
        row=1,
        col=1,
        secondary_y=True,
    )
    fig.update_yaxes(
        title_text=f"{market} · volum",
        side="right",
        showgrid=True,
        zeroline=False,
        row=2,
        col=1,
    )

    fig.update_xaxes(
        rangeslider_visible=False,
        showgrid=True,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikedash="dot",
        tickformat="%d %b\n%H:%M",
        row=1,
        col=1,
    )
    fig.update_xaxes(
        title_text="Tid · UTC",
        showgrid=True,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikedash="dot",
        tickformat="%d %b\n%H:%M",
        row=2,
        col=1,
    )

    fig.update_layout(
        template="plotly_white",
        title={
            "text": f"{market} · {timeframe} · {int(window_hours)}t",
            "x": 0.0,
            "xanchor": "left",
        },
        height=760,
        margin={"l": 78, "r": 88, "t": 76, "b": 36},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        hovermode="x",
        dragmode="pan",
        uirevision=f"TradingDesk:{market}:{timeframe}:{int(window_hours)}",
    )
    return fig
