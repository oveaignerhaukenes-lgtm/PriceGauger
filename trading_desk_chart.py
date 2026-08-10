from __future__ import annotations

from collections.abc import Mapping, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading_desk import ChartBar, normalized_close_series
from trading_desk_indicators import (
    INDICATOR_ATR,
    INDICATOR_BOLLINGER,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_MACD,
    INDICATOR_OPTIONS,
    INDICATOR_RSI,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    TechnicalIndicators,
)


OVERLAY_NORMALIZED = "Normalisert (100)"
OVERLAY_ACTUAL = "Faktisk pris"
CROSSHAIR_COLOR = "rgba(31,41,55,0.62)"
TEXT_COLOR = "#111111"
GRID_COLOR = "rgba(17,24,39,0.12)"
REFERENCE_COLOR = "rgba(17,24,39,0.48)"


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


def _axis_style() -> dict[str, object]:
    return {
        "tickfont": {"color": TEXT_COLOR, "size": 13},
        "title_font": {"color": TEXT_COLOR, "size": 13},
        "gridcolor": GRID_COLOR,
        "linecolor": "rgba(17,24,39,0.35)",
        "tickcolor": "rgba(17,24,39,0.45)",
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
    chart_height: int = 780,
    price_panel_share: float = 0.50,
    empty_message: str = "Ingen ferdige canonical 1m-bars å vise ennå.",
) -> go.Figure:
    """Build the TradingDesk chart with readable axes and dynamic indicator panels."""

    selected = set(indicator_names)
    unsupported = selected - set(INDICATOR_OPTIONS)
    if unsupported:
        raise ValueError(f"Unsupported TradingDesk indicators: {sorted(unsupported)}")

    price_share = max(0.38, min(0.68, float(price_panel_share)))
    panel_order: list[str] = []
    if INDICATOR_MACD in selected:
        panel_order.append(INDICATOR_MACD)
    if INDICATOR_RSI in selected:
        panel_order.append(INDICATOR_RSI)
    if INDICATOR_STOCHASTIC in selected:
        panel_order.append(INDICATOR_STOCHASTIC)
    if INDICATOR_ATR in selected:
        panel_order.append(INDICATOR_ATR)

    panel_rows = {name: index + 3 for index, name in enumerate(panel_order)}
    row_count = 2 + len(panel_order)
    volume_share = 0.10
    remaining = max(0.12, 1.0 - price_share - volume_share)
    panel_share = remaining / max(1, len(panel_order)) if panel_order else 0.0
    row_heights = [price_share, volume_share] + [panel_share] * len(panel_order)

    fig = make_subplots(
        rows=row_count,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
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
                    line={"width": 1.1},
                    opacity=0.72,
                    hovertemplate=f"{market} indeks<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        if indicators is not None and INDICATOR_BOLLINGER in selected:
            for name, points, dash, width in (
                ("Bollinger øvre (20,2)", indicators.bollinger_upper, "dot", 1.0),
                ("Bollinger midt (20)", indicators.bollinger_middle, "solid", 1.15),
                ("Bollinger nedre (20,2)", indicators.bollinger_lower, "dot", 1.0),
            ):
                fig.add_trace(
                    go.Scatter(
                        x=[point.bar_time for point in points],
                        y=[point.value for point in points],
                        mode="lines",
                        name=name,
                        line={"dash": dash, "width": width},
                        opacity=0.78,
                        hovertemplate=f"{name}<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.4g}}<extra></extra>",
                    ),
                    row=1,
                    col=1,
                    secondary_y=False,
                )

        if indicators is not None:
            price_overlays = (
                (INDICATOR_EMA20, "EMA 20", indicators.ema20, "#2563eb", 1.55),
                (INDICATOR_EMA50, "EMA 50", indicators.ema50, "#d97706", 1.55),
                (INDICATOR_SMA50, "SMA 50", indicators.sma50, "#7c3aed", 1.35),
            )
            for indicator, name, points, color, width in price_overlays:
                if indicator not in selected:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=[point.bar_time for point in points],
                        y=[point.value for point in points],
                        mode="lines",
                        name=name,
                        line={"color": color, "width": width},
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
                opacity=0.78,
                hovertemplate="Volum<br>%{x|%d.%m %H:%M} UTC<br>%{y}<extra></extra>",
            ),
            row=2,
            col=1,
        )

        if indicators is not None and INDICATOR_MACD in panel_rows:
            row = panel_rows[INDICATOR_MACD]
            fig.add_trace(
                go.Bar(
                    x=[point.bar_time for point in indicators.macd_histogram],
                    y=[point.value for point in indicators.macd_histogram],
                    name="MACD histogram",
                    opacity=0.72,
                    hovertemplate="MACD histogram<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.macd],
                    y=[point.value for point in indicators.macd],
                    mode="lines",
                    name="MACD (12,26)",
                    line={"color": "#2563eb", "width": 1.8},
                    hovertemplate="MACD<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.macd_signal],
                    y=[point.value for point in indicators.macd_signal],
                    mode="lines",
                    name="Signal (9)",
                    line={"color": "#dc2626", "width": 1.6},
                    hovertemplate="MACD signal<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=row,
                col=1,
            )
            fig.add_hline(y=0, line_width=0.8, line_dash="dot", line_color=REFERENCE_COLOR, row=row, col=1)

        if indicators is not None and INDICATOR_RSI in panel_rows:
            row = panel_rows[INDICATOR_RSI]
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.rsi],
                    y=[point.value for point in indicators.rsi],
                    mode="lines",
                    name="RSI (14)",
                    line={"color": "#7c3aed", "width": 1.8},
                    hovertemplate="RSI (14)<br>%{x|%d.%m %H:%M} UTC<br>%{y:.2f}<extra></extra>",
                ),
                row=row,
                col=1,
            )
            for level in (70, 30):
                fig.add_hline(y=level, line_width=0.8, line_dash="dot", line_color=REFERENCE_COLOR, row=row, col=1)

        if indicators is not None and INDICATOR_STOCHASTIC in panel_rows:
            row = panel_rows[INDICATOR_STOCHASTIC]
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.stochastic_k],
                    y=[point.value for point in indicators.stochastic_k],
                    mode="lines",
                    name="Stoch %K (14)",
                    line={"color": "#2563eb", "width": 1.7},
                ),
                row=row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.stochastic_d],
                    y=[point.value for point in indicators.stochastic_d],
                    mode="lines",
                    name="Stoch %D (3)",
                    line={"color": "#dc2626", "width": 1.5},
                ),
                row=row,
                col=1,
            )
            for level in (80, 20):
                fig.add_hline(y=level, line_width=0.8, line_dash="dot", line_color=REFERENCE_COLOR, row=row, col=1)

        if indicators is not None and INDICATOR_ATR in panel_rows:
            row = panel_rows[INDICATOR_ATR]
            fig.add_trace(
                go.Scatter(
                    x=[point.bar_time for point in indicators.atr],
                    y=[point.value for point in indicators.atr],
                    mode="lines",
                    name="ATR (14)",
                    line={"color": "#059669", "width": 1.7},
                    hovertemplate="ATR (14)<br>%{x|%d.%m %H:%M} UTC<br>%{y:.4g}<extra></extra>",
                ),
                row=row,
                col=1,
            )

        last_close = float(primary[-1].close)
        fig.add_hline(
            y=last_close,
            line_width=0.9,
            line_dash="dot",
            line_color=REFERENCE_COLOR,
            annotation_text=f"Siste {last_close:g}",
            annotation_position="top right",
            row=1,
            col=1,
        )
    else:
        fig.add_annotation(text=empty_message, xref="paper", yref="paper", x=0.5, y=0.58, showarrow=False, font={"color": TEXT_COLOR, "size": 14})

    for overlay_market, bars in overlays.items():
        if not bars:
            continue
        points = normalized_close_series(bars) if overlay_mode == OVERLAY_NORMALIZED else tuple((item.bar_time, item.close) for item in bars)
        fig.add_trace(
            go.Scatter(
                x=[stamp for stamp, _ in points],
                y=[value for _, value in points],
                mode="lines",
                name=overlay_market,
                line={"width": 1.25},
                opacity=0.82,
                hovertemplate=f"{overlay_market}<br>%{{x|%d.%m %H:%M}} UTC<br>%{{y:.4g}}<extra></extra>",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    axis_style = _axis_style()
    fig.update_yaxes(
        title_text=f"{market} · pris", side="right", showgrid=True, zeroline=False,
        row=1, col=1, secondary_y=False, **axis_style, **_crosshair_yaxis_kwargs(),
    )
    fig.update_yaxes(
        title_text=overlay_axis_title(overlay_mode), side="left", showgrid=False, zeroline=False,
        row=1, col=1, secondary_y=True, **axis_style,
    )
    fig.update_yaxes(title_text=f"{market} · volum", side="right", showgrid=True, zeroline=False, row=2, col=1, **axis_style)

    for name, row in panel_rows.items():
        kwargs: dict[str, object] = {
            "title_text": "Stoch" if name == INDICATOR_STOCHASTIC else name,
            "showgrid": True,
            "zeroline": False,
            "row": row,
            "col": 1,
            **axis_style,
            **_crosshair_yaxis_kwargs(),
        }
        if name in {INDICATOR_RSI, INDICATOR_STOCHASTIC}:
            kwargs["range"] = [0, 100]
            kwargs["tickvals"] = [20, 50, 80] if name == INDICATOR_STOCHASTIC else [30, 50, 70]
        fig.update_yaxes(**kwargs)

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
            tickfont={"color": TEXT_COLOR, "size": 12},
            title_font={"color": TEXT_COLOR, "size": 13},
            gridcolor=GRID_COLOR,
            linecolor="rgba(17,24,39,0.35)",
            row=row,
            col=1,
        )
    fig.update_xaxes(title_text="Tid · UTC", row=row_count, col=1)

    fig.update_layout(
        template="plotly_white",
        title={"text": f"{market} · {timeframe} · {int(window_hours)}t", "x": 0.0, "xanchor": "left", "font": {"color": TEXT_COLOR, "size": 17}},
        height=max(620, int(chart_height)),
        margin={"l": 74, "r": 96, "t": 66, "b": 30},
        font={"color": TEXT_COLOR, "size": 13},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0, "font": {"color": TEXT_COLOR, "size": 12}},
        hovermode="closest",
        dragmode="pan",
        paper_bgcolor="white",
        plot_bgcolor="white",
        uirevision=f"TradingDesk:{market}:{timeframe}:{int(window_hours)}:{','.join(sorted(selected))}:{int(chart_height)}:{price_share:.2f}",
    )
    return fig
