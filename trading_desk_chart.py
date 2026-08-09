from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading_desk import ChartBar, normalized_close_series
from trading_desk_indicators import (
    INDICATOR_BOLLINGER,
    INDICATOR_MACD,
    INDICATOR_RSI,
    TechnicalIndicators,
)


OVERLAY_NORMALIZED = "Normalisert (100)"
OVERLAY_ACTUAL = "Faktisk pris"
CROSSHAIR_COLOR = "rgba(71,85,105,0.55)"
INDICATOR_OPACITY = 0.62
REFERENCE_OPACITY = 0.42


def overlay_axis_title(mode: str) -> str:
    if mode == OVERLAY_NORMALIZED:
        return "Overlay · indeks (100 = start)"
    if mode == OVERLAY_ACTUAL:
        return "Overlay · faktisk pris"
    raise ValueError(f"Unsupported TradingDesk overlay mode: {mode}")


def _crosshair_yaxis_kwargs() -> dict[str, object]:
    return {
        "showspikes": True,
        "spikemode": "across+toaxis",
        "spikesnap": "cursor",
        "spikedash": "dot",
        "spikecolor": CROSSHAIR_COLOR,
        "spikethickness": 1,
        "hoverformat": ".4~g",
    }


def build_trading_desk_figure(
    *,
    market: str,
    timeframe: str,
    window_hours: int,
    primary: Sequence[ChartBar],
    overlays: Mapping[str, Sequence[ChartBar]],
    overlay_mode: str,
    indicators: TechnicalIndicators | None = None,
    indicator_names: Sequence[str] = (),
    empty_message: str = "Ingen ferdige canonical 1m-bars å vise ennå.",
) -> go.Figure:
    """Build the operational TradingDesk chart with explicit axis ownership.

    Primary-market candles use the right-hand price axis. Cross-market overlays
    use the separate left-hand axis. Volume has its own lower panel. Bollinger
    stays on the primary price panel, while MACD and RSI receive dedicated panels.
    """

    selected = set(indicator_names)
    unsupported = selected - {INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI}
    if unsupported:
        raise ValueError(f"Unsupported TradingDesk indicators: {sorted(unsupported)}")

    overlay_title = overlay_axis_title(overlay_mode)
    macd_row = 3 if INDICATOR_MACD in selected else None
    rsi_row = 3 + (1 if macd_row is not None else 0) if INDICATOR_RSI in selected else None
    row_count = 2 + int(macd_row is not None) + int(rsi_row is not None)
    row_heights = [0.66, 0.14]
    if macd_row is not None:
        row_heights.append(0.18)
    if rsi_row is not None:
        row_heights.append(0.16)

    fig = make_subplots(
        rows=row_count,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=row_heights,
        specs=[[{"secondary_y": True}]] + [[{}] for _ in range(row_count - 1)],
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
                    line={"width": 1.0},
                    opacity=0.55,
                    hovertemplate=f"{market} indeks<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        if indicators is not None and INDICATOR_BOLLINGER in selected:
            for name, points, dash, width in (
                ("Bollinger øvre (20,2)", indicators.bollinger_upper, "dot", 0.8),
                ("Bollinger midt (20)", indicators.bollinger_middle, "solid", 0.9),
                ("Bollinger nedre (20,2)", indicators.bollinger_lower, "dot", 0.8),
            ):
                fig.add_trace(
                    go.Scatter(
                        x=[point.bar_time for point in points],
                        y=[point.value for point in points],
                        mode="lines",
                        name=name,
                        line={"dash": dash, "width": width},
                        opacity=INDICATOR_OPACITY,
                        hovertemplate=f"{name}<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.4g}}<extra></extra>",
                    ),
                    row=1,
                    col=1,
                    secondary_y=False,
                )

        fig.add_trace(
            go.Bar(
                x=[item.bar_time for item in primary],
                y=[item.volume for item in primary],
                name=f"{market} · volum",
                opacity=0.72,
                hovertemplate="Volum<br>%{x|%d.%m %H:%M} UTC<br>%{y}<extra></extra>",
            ),
            row=2,
            col=1,
        )

        if indicators is not None and macd_row is not None:
            fig.add_trace(
                go.Bar(
                    x=[point.bar_time for point in indicators.macd_histogram],
                    y=[point.value for point in indicators.macd_histogram],
                    name="MACD histogram",
                    opacity=0.52,
                    hovertemplate="MACD histogram<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=macd_row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.macd],
                    y=[point.value for point in indicators.macd],
                    mode="lines",
                    name="MACD (12,26)",
                    line={"width": 1.1},
                    opacity=INDICATOR_OPACITY,
                    hovertemplate="MACD<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=macd_row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.macd_signal],
                    y=[point.value for point in indicators.macd_signal],
                    mode="lines",
                    name="Signal (9)",
                    line={"width": 1.1},
                    opacity=INDICATOR_OPACITY,
                    hovertemplate="MACD signal<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=macd_row,
                col=1,
            )
            fig.add_hline(
                y=0,
                line_width=0.8,
                line_dash="dot",
                opacity=REFERENCE_OPACITY,
                row=macd_row,
                col=1,
            )

        if indicators is not None and rsi_row is not None:
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.rsi],
                    y=[point.value for point in indicators.rsi],
                    mode="lines",
                    name="RSI (14)",
                    line={"width": 1.1},
                    opacity=INDICATOR_OPACITY,
                    hovertemplate="RSI (14)<br>%{x|%d.%m %H:%M} UTC<br>%{y:.2f}<extra></extra>",
                ),
                row=rsi_row,
                col=1,
            )
            fig.add_hline(
                y=70,
                line_width=0.8,
                line_dash="dot",
                opacity=REFERENCE_OPACITY,
                row=rsi_row,
                col=1,
            )
            fig.add_hline(
                y=30,
                line_width=0.8,
                line_dash="dot",
                opacity=REFERENCE_OPACITY,
                row=rsi_row,
                col=1,
            )

        last_close = float(primary[-1].close)
        fig.add_hline(
            y=last_close,
            line_width=0.8,
            line_dash="dot",
            opacity=0.6,
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
                line={"width": 1.0},
                opacity=0.58,
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
        **_crosshair_yaxis_kwargs(),
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
    if macd_row is not None:
        fig.update_yaxes(
            title_text="MACD",
            showgrid=True,
            zeroline=False,
            row=macd_row,
            col=1,
            **_crosshair_yaxis_kwargs(),
        )
    if rsi_row is not None:
        fig.update_yaxes(
            title_text="RSI",
            range=[0, 100],
            tickvals=[30, 50, 70],
            showgrid=True,
            zeroline=False,
            row=rsi_row,
            col=1,
            **_crosshair_yaxis_kwargs(),
        )

    for row in range(1, row_count + 1):
        fig.update_xaxes(
            rangeslider_visible=False if row == 1 else None,
            showgrid=True,
            showspikes=True,
            spikemode="across+toaxis",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor=CROSSHAIR_COLOR,
            spikethickness=1,
            tickformat="%d %b\n%H:%M",
            row=row,
            col=1,
        )
    fig.update_xaxes(title_text="Tid · UTC", row=row_count, col=1)

    fig.update_layout(
        template="plotly_white",
        title={
            "text": f"{market} · {timeframe} · {int(window_hours)}t",
            "x": 0.0,
            "xanchor": "left",
        },
        height=760 + 150 * int(macd_row is not None) + 130 * int(rsi_row is not None),
        margin={"l": 78, "r": 88, "t": 76, "b": 36},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        hovermode="closest",
        dragmode="pan",
        uirevision=f"TradingDesk:{market}:{timeframe}:{int(window_hours)}:{','.join(sorted(selected))}",
    )
    return fig
