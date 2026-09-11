from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from autotrader_ai_baseline_v1 import STRATEGY_KEY as HOLISTIC_AI_STRATEGY_KEY
from autotrader_hybrid_replay_v1 import replay_hybrid_models_v1
from autotrader_macd_supervisor_replay_v1 import (
    replay_macd_supervisor_v1,
    summarize_macd_supervisor_frame_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from trading_desk_v2_context import TradingDeskV2Context

RULE_NAME = "Dum MACD"
ADAPTIVE_NAME = "MACD-adaptiv"
HOLISTIC_NAME = "Holistisk AI"
ALL_MODELS = (RULE_NAME, ADAPTIVE_NAME, HOLISTIC_NAME)


def _stamp(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _load_holistic_decisions(instrument_id: int, start: datetime, end: datetime) -> tuple[dict, ...]:
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT action_at, price, target_direction, confidence, summary
                FROM pg_v2_autotrader_ai_baseline_samples
                WHERE strategy_key = ? AND instrument_id = ?
                  AND action_at >= ? AND action_at <= ?
                ORDER BY action_at ASC
                """,
                (HOLISTIC_AI_STRATEGY_KEY, int(instrument_id), start, end),
            ).fetchall()
    except Exception:
        return ()
    result = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0], "price": row[1], "target_direction": row[2],
            "confidence": row[3], "summary": row[4],
        }
        word = str(values["target_direction"]).upper()
        target = 1 if word == "LONG" else -1 if word == "SHORT" else 0
        result.append({
            "at": _stamp(values["action_at"]),
            "price": float(values["price"]),
            "target": target,
            "confidence": float(values["confidence"]),
            "summary": str(values["summary"]),
        })
    return tuple(result)


def _target_frame(price_frame: pd.DataFrame, decisions: tuple[dict, ...]) -> pd.DataFrame:
    frame = price_frame[["PRICE"]].copy()
    target = pd.Series(0.0, index=frame.index, dtype="float64")
    if not decisions:
        frame["TARGET"] = target
        return frame
    ordered = sorted(decisions, key=lambda item: item["at"])
    current = 0
    cursor = 0
    for index, at in enumerate(frame.index):
        stamp = _stamp(at)
        while cursor < len(ordered) and ordered[cursor]["at"] <= stamp:
            proposed = int(ordered[cursor]["target"])
            if proposed in (-1, 0, 1):
                current = proposed
            cursor += 1
        target.iloc[index] = current
    frame["TARGET"] = target
    return frame


def _events_from_target(frame: pd.DataFrame) -> tuple[dict, ...]:
    events = []
    previous = 0
    for at, row in frame.iterrows():
        current = int(row["TARGET"])
        if current != previous and current in (-1, 1):
            events.append({"at": _stamp(at), "price": float(row["PRICE"]), "target": current})
        previous = current
    return tuple(events)


def _figure(price_frame: pd.DataFrame, event_sets: dict[str, tuple[dict, ...]], visible_models) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=price_frame.index,
        y=price_frame["PRICE"],
        mode="lines",
        name="Pris",
        line={"width": 1.5},
    ))
    styles = {
        RULE_NAME: {"size": 10, "open": True, "prefix": "Rule"},
        ADAPTIVE_NAME: {"size": 12, "open": False, "prefix": "Adaptiv"},
        HOLISTIC_NAME: {"size": 15, "open": False, "prefix": "AI"},
    }
    # Draw the largest markers first so smaller baseline markers remain visible when
    # multiple traders choose the same timestamp and price.
    for model in (HOLISTIC_NAME, ADAPTIVE_NAME, RULE_NAME):
        if model not in visible_models:
            continue
        style = styles[model]
        events = event_sets.get(model, ())
        for direction, sign, base_symbol in (("LONG", 1, "triangle-up"), ("SHORT", -1, "triangle-down")):
            selected = [item for item in events if int(item["target"]) == sign]
            if not selected:
                continue
            symbol = f"{base_symbol}-open" if style["open"] else base_symbol
            figure.add_trace(go.Scatter(
                x=[item["at"] for item in selected],
                y=[item["price"] for item in selected],
                mode="markers",
                name=f"{style['prefix']} {direction}",
                marker={"symbol": symbol, "size": style["size"], "line": {"width": 2 if style["open"] else 1}},
            ))
    figure.update_layout(
        height=390,
        margin={"l": 8, "r": 8, "t": 28, "b": 8},
        legend={"orientation": "h", "y": 1.02, "x": 0},
        uirevision="three-trader-observation-v1",
        xaxis_title=None,
        yaxis_title=None,
    )
    return figure


def _render_metrics(name: str, frame: pd.DataFrame, *, cost_bps: float) -> None:
    summary = summarize_macd_supervisor_frame_v1(frame, cost_bps_per_leg=cost_bps)
    st.markdown(f"**{name}**")
    cols = st.columns(5)
    cols[0].metric("Treff", f"{summary.win_rate_pct:.1f}%")
    cols[1].metric("Retur", f"{summary.return_pct:+.1f}%")
    cols[2].metric("Capture", f"{summary.capture_area_pct:.1f}%")
    cols[3].metric("Max DD", f"{summary.max_drawdown_pct:.1f}%")
    cols[4].metric("Skift", str(summary.switches))


def render_tradingdesk_three_trader_lab_v1(context: TradingDeskV2Context) -> None:
    instrument_id = context.instrument_id
    if instrument_id is None:
        return

    with st.container(border=True):
        st.markdown("### Tre tradere · samme marked")
        st.caption(
            "Sammenligner tre uavhengige spor på samme canonical prisserie: enkel MACD-supervisor, "
            "adaptiv MACD-periode og den bredere holistiske AI-baselinen. Analyse-only; ingen av disse markørene sender ordre."
        )
        controls = st.columns([1, 1, 2])
        with controls[0]:
            hours = int(st.selectbox(
                "Vindu", (6, 12, 24, 48), index=2,
                format_func=lambda value: f"{value} t",
                key=f"three-trader-window-{instrument_id}",
            ))
        with controls[1]:
            cost_bps = float(st.number_input(
                "Kostnad / ordrebein (bps)", 0.0, 25.0, 0.0, 0.1,
                key=f"three-trader-cost-{instrument_id}",
            ))
        with controls[2]:
            visible = st.multiselect(
                "Vis / plott",
                ALL_MODELS,
                default=ALL_MODELS,
                key=f"three-trader-visible-{instrument_id}",
            )

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours + 18)
        try:
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(instrument_id), start=start, end=end, limit=12000
            )
            rule_full, rule_switches, _ = replay_macd_supervisor_v1(bars, cost_bps_per_leg=cost_bps)
            adaptive_full, _ = replay_hybrid_models_v1(bars, cost_bps_per_leg=cost_bps)
        except Exception as exc:
            st.caption(f"Tre-trader-lab venter på nok canonical data: {exc}")
            return

        visible_since = _stamp(end - timedelta(hours=hours))
        rule_frame = rule_full[rule_full.index >= visible_since][["PRICE", "TARGET"]].copy()
        adaptive_slice = adaptive_full[adaptive_full.index >= visible_since]
        adaptive_frame = pd.DataFrame(index=adaptive_slice.index)
        adaptive_frame["PRICE"] = adaptive_slice["PRICE"]
        adaptive_frame["TARGET"] = adaptive_slice["TARGET_MACD-A"]

        decisions = _load_holistic_decisions(int(instrument_id), end - timedelta(hours=hours), end)
        holistic_frame = _target_frame(rule_frame, decisions)

        rule_events = tuple(
            {"at": _stamp(item.at), "price": float(item.price), "target": int(item.target)}
            for item in rule_switches if _stamp(item.at) >= visible_since
        )
        adaptive_events = _events_from_target(adaptive_frame)
        holistic_events = tuple(
            item for item in decisions if int(item["target"]) in (-1, 1)
        )
        event_sets = {
            RULE_NAME: rule_events,
            ADAPTIVE_NAME: adaptive_events,
            HOLISTIC_NAME: holistic_events,
        }

        if RULE_NAME in visible:
            _render_metrics(RULE_NAME, rule_frame, cost_bps=cost_bps)
        if ADAPTIVE_NAME in visible:
            _render_metrics(ADAPTIVE_NAME, adaptive_frame, cost_bps=cost_bps)
        if HOLISTIC_NAME in visible:
            if decisions:
                _render_metrics(HOLISTIC_NAME, holistic_frame, cost_bps=cost_bps)
            else:
                st.markdown(f"**{HOLISTIC_NAME}**")
                st.caption("Ingen lagrede holistiske AI-beslutninger i valgt vindu ennå.")

        st.plotly_chart(
            _figure(rule_frame, event_sets, visible),
            width="stretch",
            config={"displayModeBar": False},
            key=f"three-trader-chart-{instrument_id}",
        )
        st.caption(
            "Åpne små trekanter = dum MACD · mellomstore trekanter = MACD-adaptiv · store trekanter = holistisk AI. "
            "Samme tidspunkt/pris kan overlappe; størrelsesrekkefølgen gjør alle tre synlige."
        )


__all__ = ["render_tradingdesk_three_trader_lab_v1"]
