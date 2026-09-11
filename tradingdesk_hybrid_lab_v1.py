from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

from autotrader_hybrid_replay_v1 import DEFAULT_WEIGHTS_V1, MODEL_NAMES_V1, replay_hybrid_models_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from trading_desk_v2_context import TradingDeskV2Context


@dataclass(frozen=True, slots=True)
class HybridLabConfigV1:
    instrument_id: int
    macd2: float = 50.0
    macd2_10: float = 20.0
    macd2_s: float = 30.0
    macd_a: float = 0.0
    threshold: float = 0.10
    cost_bps_per_leg: float = 0.0

    @property
    def weights(self) -> dict[str, float]:
        return {
            "MACD2": float(self.macd2),
            "MACD2-10": float(self.macd2_10),
            "MACD2-S": float(self.macd2_s),
            "MACD-A": float(self.macd_a),
        }


def ensure_hybrid_lab_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_hybrid_lab_config (
                instrument_id BIGINT PRIMARY KEY,
                macd2 DOUBLE PRECISION NOT NULL DEFAULT 50,
                macd2_10 DOUBLE PRECISION NOT NULL DEFAULT 20,
                macd2_s DOUBLE PRECISION NOT NULL DEFAULT 30,
                macd_a DOUBLE PRECISION NOT NULL DEFAULT 0,
                threshold DOUBLE PRECISION NOT NULL DEFAULT 0.10,
                cost_bps_per_leg DOUBLE PRECISION NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def load_hybrid_lab_config_v1(instrument_id: int) -> HybridLabConfigV1:
    ensure_hybrid_lab_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT macd2, macd2_10, macd2_s, macd_a, threshold, cost_bps_per_leg
            FROM pg_v2_hybrid_lab_config WHERE instrument_id = ?
            """,
            (int(instrument_id),),
        ).fetchone()
    if row is None:
        return HybridLabConfigV1(instrument_id=int(instrument_id))
    values = dict(row) if isinstance(row, dict) else {
        "macd2": row[0], "macd2_10": row[1], "macd2_s": row[2], "macd_a": row[3],
        "threshold": row[4], "cost_bps_per_leg": row[5],
    }
    return HybridLabConfigV1(
        instrument_id=int(instrument_id),
        macd2=float(values["macd2"]),
        macd2_10=float(values["macd2_10"]),
        macd2_s=float(values["macd2_s"]),
        macd_a=float(values["macd_a"]),
        threshold=float(values["threshold"]),
        cost_bps_per_leg=float(values["cost_bps_per_leg"]),
    )


def save_hybrid_lab_config_v1(config: HybridLabConfigV1) -> None:
    ensure_hybrid_lab_schema_v1()
    if sum(max(0.0, value) for value in config.weights.values()) <= 0.0:
        raise ValueError("Minst én hybridvekt må være større enn 0")
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_hybrid_lab_config(
                instrument_id, macd2, macd2_10, macd2_s, macd_a,
                threshold, cost_bps_per_leg, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (instrument_id) DO UPDATE SET
                macd2=EXCLUDED.macd2,
                macd2_10=EXCLUDED.macd2_10,
                macd2_s=EXCLUDED.macd2_s,
                macd_a=EXCLUDED.macd_a,
                threshold=EXCLUDED.threshold,
                cost_bps_per_leg=EXCLUDED.cost_bps_per_leg,
                updated_at=now()
            """,
            (
                int(config.instrument_id), float(config.macd2), float(config.macd2_10),
                float(config.macd2_s), float(config.macd_a), float(config.threshold),
                float(config.cost_bps_per_leg),
            ),
        )


def _replay_figure(frame) -> go.Figure:
    figure = go.Figure()
    order = ("HYBRID", "MACD2", "MACD2-10", "MACD2-S", "MACD-A")
    for name in order:
        if name not in frame.columns:
            continue
        figure.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame[name],
                mode="lines",
                name=name,
                line={"width": 3 if name == "HYBRID" else 1.3},
            )
        )
    figure.add_hline(y=0.0, line_width=1, line_dash="dot")
    figure.update_layout(
        height=330,
        margin={"l": 8, "r": 8, "t": 28, "b": 8},
        legend={"orientation": "h", "y": 1.02, "x": 0},
        yaxis_title="Signalavkastning %",
        xaxis_title=None,
    )
    return figure


def _score_figure(frame, *, threshold: float) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(x=frame.index, y=frame["HYBRID_SCORE"], mode="lines", name="HYBRID score")
    )
    band = max(0.0, min(1.0, float(threshold)))
    figure.add_hline(y=band, line_width=1, line_dash="dot")
    figure.add_hline(y=-band, line_width=1, line_dash="dot")
    figure.update_layout(
        height=190,
        margin={"l": 8, "r": 8, "t": 20, "b": 8},
        yaxis={"range": [-1.05, 1.05], "title": "score"},
        xaxis_title=None,
        showlegend=False,
    )
    return figure


def _visible_return_pct(series) -> float:
    if len(series) < 2:
        return 0.0
    start_equity = 1.0 + (float(series.iloc[0]) / 100.0)
    end_equity = 1.0 + (float(series.iloc[-1]) / 100.0)
    if start_equity <= 0.0:
        return 0.0
    return ((end_equity / start_equity) - 1.0) * 100.0


def render_tradingdesk_hybrid_lab_v1(context: TradingDeskV2Context) -> None:
    instrument_id = context.instrument_id
    if instrument_id is None:
        return
    try:
        persisted = load_hybrid_lab_config_v1(instrument_id)
    except Exception as exc:
        st.caption(f"Hybrid Lab utilgjengelig: {exc}")
        return

    with st.expander("Hybrid Lab · vekting og test", expanded=False):
        st.caption(
            "Vektene kombinerer signalene til én LONG/SHORT-beslutning. De deler aldri Saxo-posisjonen i flere strategier."
        )
        columns = st.columns(4)
        values: dict[str, float] = {}
        defaults = persisted.weights
        for column, name in zip(columns, MODEL_NAMES_V1):
            with column:
                values[name] = float(
                    st.number_input(
                        name,
                        min_value=0.0,
                        max_value=100.0,
                        value=float(defaults.get(name, DEFAULT_WEIGHTS_V1[name])),
                        step=5.0,
                        key=f"hybrid-weight-{instrument_id}-{name}",
                    )
                )

        left, middle, right = st.columns([1, 1, 1])
        with left:
            threshold = float(
                st.slider(
                    "Uenighetsbånd",
                    min_value=0.0,
                    max_value=0.50,
                    value=float(persisted.threshold),
                    step=0.01,
                    key=f"hybrid-threshold-{instrument_id}",
                )
            )
        with middle:
            cost_bps = float(
                st.number_input(
                    "Testkostnad / ordrebein (bps)",
                    min_value=0.0,
                    max_value=25.0,
                    value=float(persisted.cost_bps_per_leg),
                    step=0.1,
                    key=f"hybrid-cost-{instrument_id}",
                )
            )
        with right:
            lookback_hours = int(
                st.selectbox(
                    "Testvindu",
                    options=(6, 12, 24, 48),
                    index=2,
                    format_func=lambda value: f"{value} t",
                    key=f"hybrid-window-{instrument_id}",
                )
            )

        config = HybridLabConfigV1(
            instrument_id=int(instrument_id),
            macd2=values["MACD2"],
            macd2_10=values["MACD2-10"],
            macd2_s=values["MACD2-S"],
            macd_a=values["MACD-A"],
            threshold=threshold,
            cost_bps_per_leg=cost_bps,
        )
        if st.button("Lagre hybrid", key=f"hybrid-save-{instrument_id}"):
            try:
                save_hybrid_lab_config_v1(config)
                st.success("Hybridvekter lagret")
            except Exception as exc:
                st.error(str(exc))

        if sum(config.weights.values()) <= 0.0:
            st.warning("Sett minst én vekt over 0 for å teste modellen.")
            return

        end = datetime.now(timezone.utc)
        # Extra warmup makes the visible replay independent of EMA/Stochastic startup.
        start = end - timedelta(hours=lookback_hours + 12)
        try:
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(instrument_id), start=start, end=end, limit=5000
            )
            replay, summary = replay_hybrid_models_v1(
                bars,
                weights=config.weights,
                hybrid_threshold=config.threshold,
                cost_bps_per_leg=config.cost_bps_per_leg,
            )
        except Exception as exc:
            st.caption(f"Ikke nok canonical data til hybridtest ennå: {exc}")
            return

        visible_since = end - timedelta(hours=lookback_hours)
        visible = replay[replay.index >= visible_since]
        if visible.empty:
            st.caption("Ingen datapunkter i valgt testvindu.")
            return

        st.plotly_chart(_replay_figure(visible), width="stretch", config={"displayModeBar": False})
        hybrid_return = _visible_return_pct(visible["HYBRID"])
        st.caption(
            f"HYBRID {hybrid_return:+.2f}% i vist vindu · {summary.switches['HYBRID']} skift i hele replayet. "
            "Dette er normalisert signalreplay før gearing, ikke Saxo-konto-P/L."
        )
        with st.expander("Hybrid-score", expanded=False):
            st.plotly_chart(
                _score_figure(visible, threshold=config.threshold),
                width="stretch",
                config={"displayModeBar": False},
            )
            st.caption("+1 = full LONG-støtte, −1 = full SHORT-støtte. Innen uenighetsbåndet beholdes forrige retning.")


__all__ = [
    "HybridLabConfigV1",
    "ensure_hybrid_lab_schema_v1",
    "load_hybrid_lab_config_v1",
    "render_tradingdesk_hybrid_lab_v1",
    "save_hybrid_lab_config_v1",
]
