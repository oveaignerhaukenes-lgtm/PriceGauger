from __future__ import annotations

from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from autotrader_macd_supervisor_replay_v1 import (
    replay_macd_supervisor_v1,
    summarize_macd_supervisor_frame_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from trading_desk_v2_context import TradingDeskV2Context


def _supervisor_figure(frame, switches) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["PRICE"],
            mode="lines",
            name="Price",
            line={"width": 1.5},
        )
    )
    longs = [item for item in switches if item.target > 0]
    shorts = [item for item in switches if item.target < 0]
    if longs:
        figure.add_trace(
            go.Scatter(
                x=[item.at for item in longs],
                y=[item.price for item in longs],
                mode="markers",
                name="LONG",
                marker={"symbol": "triangle-up", "size": 11},
            )
        )
    if shorts:
        figure.add_trace(
            go.Scatter(
                x=[item.at for item in shorts],
                y=[item.price for item in shorts],
                mode="markers",
                name="SHORT",
                marker={"symbol": "triangle-down", "size": 11},
            )
        )
    figure.update_layout(
        height=300,
        margin={"l": 8, "r": 8, "t": 26, "b": 8},
        legend={"orientation": "h", "y": 1.02, "x": 0},
        xaxis_title=None,
        yaxis_title=None,
    )
    return figure


def _metric_value(value: float, suffix: str = "%") -> str:
    return f"{value:+.1f}{suffix}" if value != 0.0 else f"0.0{suffix}"


def render_tradingdesk_macd_supervisor_lab_v1(context: TradingDeskV2Context) -> None:
    instrument_id = context.instrument_id
    if instrument_id is None:
        return

    with st.container(border=True):
        st.markdown("### MACD Supervisor · observasjonslab")
        st.caption(
            "Analysemodell uten execution authority. Leser lukket 1m/2m/5m/10m/15m/30m MACD samtidig: "
            "langsomme perioder gir kontekst, raske/mellomperioder varsler endring som sprer seg oppover."
        )

        controls = st.columns([1, 1, 2])
        with controls[0]:
            lookback_hours = int(
                st.selectbox(
                    "Testvindu",
                    options=(6, 12, 24, 48),
                    index=2,
                    format_func=lambda value: f"{value} t",
                    key=f"macd-supervisor-window-{instrument_id}",
                )
            )
        with controls[1]:
            cost_bps = float(
                st.number_input(
                    "Kostnad / ordrebein (bps)",
                    min_value=0.0,
                    max_value=25.0,
                    value=0.0,
                    step=0.1,
                    key=f"macd-supervisor-cost-{instrument_id}",
                )
            )
        with controls[2]:
            st.caption(
                "Mål: capture-area > 50 %. 0 % betyr at riktig og feil side av bevegelsen omtrent kansellerer hverandre."
            )

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=lookback_hours + 18)
        try:
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(instrument_id),
                start=start,
                end=end,
                limit=12000,
            )
            replay, switches, _ = replay_macd_supervisor_v1(
                bars,
                cost_bps_per_leg=cost_bps,
            )
        except Exception as exc:
            st.caption(f"MACD Supervisor venter på nok canonical data: {exc}")
            return

        visible_since = end - timedelta(hours=lookback_hours)
        visible = replay[replay.index >= visible_since]
        visible_switches = tuple(item for item in switches if item.at >= visible_since)
        if visible.empty:
            st.caption("Ingen datapunkter i valgt testvindu.")
            return
        summary = summarize_macd_supervisor_frame_v1(visible, cost_bps_per_leg=cost_bps)

        metric_cols = st.columns(6)
        metric_cols[0].metric("Treff", f"{summary.win_rate_pct:.1f}%")
        metric_cols[1].metric("Fortjeneste", _metric_value(summary.return_pct))
        metric_cols[2].metric("Capture-area", f"{summary.capture_area_pct:.1f}%")
        metric_cols[3].metric("Tid i pluss", f"{summary.profitable_time_pct:.1f}%")
        metric_cols[4].metric("Max DD", f"{summary.max_drawdown_pct:.1f}%")
        metric_cols[5].metric("Skift", str(len(visible_switches)))

        if summary.capture_area_pct >= 50.0:
            st.success("Capture-area er over 50 %-kravet i valgt vindu.")
        else:
            st.warning("Capture-area er under 50 %-kravet. Modellen er fortsatt observasjon/test.")

        st.plotly_chart(
            _supervisor_figure(visible, visible_switches),
            width="stretch",
            config={"displayModeBar": False},
        )
        st.caption(
            "Pil opp = modellen skifter LONG. Pil ned = modellen skifter SHORT. Avstanden mellom motsatte piler viser visuelt hvor mye av bevegelsen modellen holdt."
        )

        with st.expander("Beslutninger · traverser skiftene", expanded=True):
            if not visible_switches:
                st.caption("Ingen skift i valgt vindu.")
                return
            nav_key = f"macd-supervisor-nav-{instrument_id}"
            if nav_key not in st.session_state:
                st.session_state[nav_key] = len(visible_switches) - 1
            st.session_state[nav_key] = max(0, min(int(st.session_state[nav_key]), len(visible_switches) - 1))

            prev_col, next_col, label_col = st.columns([1, 1, 5])
            with prev_col:
                if st.button("← Forrige", key=f"macd-supervisor-prev-{instrument_id}"):
                    st.session_state[nav_key] = max(0, int(st.session_state[nav_key]) - 1)
            with next_col:
                if st.button("Neste →", key=f"macd-supervisor-next-{instrument_id}"):
                    st.session_state[nav_key] = min(len(visible_switches) - 1, int(st.session_state[nav_key]) + 1)
            selected = visible_switches[int(st.session_state[nav_key])]
            with label_col:
                direction = "LONG" if selected.target > 0 else "SHORT"
                st.markdown(
                    f"**{int(st.session_state[nav_key]) + 1}/{len(visible_switches)} · {direction} · "
                    f"{selected.at.strftime('%Y-%m-%d %H:%M UTC')}**"
                )

            st.write(selected.explanation)
            score_cols = st.columns(4)
            score_cols[0].metric("Total score", f"{selected.score:+.2f}")
            score_cols[1].metric("Confidence", f"{selected.confidence:.2f}")
            score_cols[2].metric("Slow context", f"{selected.context_score:+.2f}")
            score_cols[3].metric("Fast/mid change", f"{selected.change_score:+.2f}")

            rows = []
            for minutes in (1, 2, 5, 10, 15, 30):
                rows.append(
                    {
                        "TF": f"{minutes}m",
                        "MACD spread": round(selected.spreads[minutes], 6),
                        "Δ spread": round(selected.slopes[minutes], 6),
                    }
                )
            st.dataframe(rows, width="stretch", hide_index=True)

        st.caption(
            "Observasjonslab: ingen knapp eller kodebane her kan sende ordre til Saxo. Nye indikatorer legges til én om gangen slik at effekten kan måles separat."
        )


__all__ = ["render_tradingdesk_macd_supervisor_lab_v1"]
