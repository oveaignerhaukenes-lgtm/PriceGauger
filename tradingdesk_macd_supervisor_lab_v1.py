from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from autotrader_macd_supervisor_memory_v1 import persist_supervisor_replay_memory_v1
from autotrader_macd_supervisor_reflection_v1 import (
    load_supervisor_reflections_v1,
    reflect_pending_supervisor_memories_v1,
)
from autotrader_macd_supervisor_replay_v1 import replay_macd_supervisor_v1, summarize_macd_supervisor_frame_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from trading_desk_v2_context import TradingDeskV2Context

RULE_NAME = "Regelbasert MACD"
AI_NAME = "AI-refleksjon"


def _stamp(value) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def _reflection_by_stamp(reflections: dict[str, dict]) -> dict[pd.Timestamp, dict]:
    return {_stamp(key): value for key, value in reflections.items()}


def _ai_variant(frame: pd.DataFrame, switches, reflections: dict[str, dict]):
    result = frame.copy()
    reflected = _reflection_by_stamp(reflections)
    rule_events = {_stamp(item.at): item for item in switches}
    current = 0
    targets = []
    ai_events = []
    for at, row in result.iterrows():
        stamp = _stamp(at)
        event = rule_events.get(stamp)
        if event is not None:
            recommendation = reflected.get(stamp)
            desired = int(event.target)
            if recommendation is not None:
                proposed = int(recommendation["target"])
                if proposed in (-1, 1):
                    desired = proposed
                elif current in (-1, 1):
                    desired = current
            if desired != current:
                current = desired
                ai_events.append({"at": stamp, "price": float(row["PRICE"]), "target": current})
        elif current == 0:
            current = int(row["TARGET"])
        targets.append(current)
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    return result, tuple(ai_events)


def _figure(frame, rule_switches, ai_switches, visible_models) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame.index, y=frame["PRICE"], mode="lines", name="Price", line={"width": 1.5}))
    groups = []
    if RULE_NAME in visible_models:
        groups.append(("Rule", rule_switches, 10))
    if AI_NAME in visible_models:
        groups.append(("AI", ai_switches, 14))
    for label, events, size in groups:
        for direction, sign, symbol in (("LONG", 1, "triangle-up"), ("SHORT", -1, "triangle-down")):
            selected = [item for item in events if int(item.target if hasattr(item, "target") else item["target"]) == sign]
            if selected:
                fig.add_trace(go.Scatter(
                    x=[item.at if hasattr(item, "at") else item["at"] for item in selected],
                    y=[item.price if hasattr(item, "price") else item["price"] for item in selected],
                    mode="markers", name=f"{label} {direction}", marker={"symbol": symbol, "size": size},
                ))
    fig.update_layout(height=320, margin={"l":8,"r":8,"t":26,"b":8}, legend={"orientation":"h","y":1.02,"x":0})
    return fig


def _render_metrics(label: str, summary) -> None:
    st.markdown(f"**{label}**")
    cols = st.columns(6)
    cols[0].metric("Treff", f"{summary.win_rate_pct:.1f}%")
    cols[1].metric("Fortjeneste", f"{summary.return_pct:+.1f}%")
    cols[2].metric("Capture-area", f"{summary.capture_area_pct:.1f}%")
    cols[3].metric("Tid i pluss", f"{summary.profitable_time_pct:.1f}%")
    cols[4].metric("Max DD", f"{summary.max_drawdown_pct:.1f}%")
    cols[5].metric("Skift", str(summary.switches))


def render_tradingdesk_macd_supervisor_lab_v1(context: TradingDeskV2Context) -> None:
    instrument_id = context.instrument_id
    if instrument_id is None:
        return
    with st.container(border=True):
        st.markdown("### MACD Supervisor · observasjonslab")
        st.caption("Sammenlign stabil regelmotor mot AI-refleksjon med episodisk minne på identiske markedsdata.")
        controls = st.columns([1,1,2])
        with controls[0]:
            lookback_hours = int(st.selectbox("Testvindu", (6,12,24,48), index=2, format_func=lambda v:f"{v} t", key=f"macd-supervisor-window-{instrument_id}"))
        with controls[1]:
            cost_bps = float(st.number_input("Kostnad / skiftebein (bps)", 0.0, 25.0, 0.0, 0.1, key=f"macd-supervisor-cost-{instrument_id}"))
        with controls[2]:
            visible_models = st.multiselect("Vis / plott modeller", (RULE_NAME, AI_NAME), default=(RULE_NAME, AI_NAME), key=f"macd-supervisor-models-{instrument_id}")
            st.caption("Capture-area > 50 % er foreløpig brukbarhetskrav.")

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=lookback_hours + 18)
        try:
            bars = CanonicalMarketBarStoreV2().load_instrument_range(instrument_id=int(instrument_id), start=start, end=end, limit=12000)
            replay, switches, _ = replay_macd_supervisor_v1(bars, cost_bps_per_leg=cost_bps)
            persist_supervisor_replay_memory_v1(instrument_id=int(instrument_id), replay=replay, switches=switches)
            if AI_NAME in visible_models and st.button("Reflekter nye skift", key=f"macd-supervisor-reflect-{instrument_id}"):
                saved = reflect_pending_supervisor_memories_v1(limit=4)
                st.toast(f"AI-refleksjon lagret for {saved} episoder")
            reflections = load_supervisor_reflections_v1(instrument_id=int(instrument_id))
        except Exception as exc:
            st.caption(f"Supervisor-lab venter på data/minne: {exc}")
            return

        visible_since = _stamp(end - timedelta(hours=lookback_hours))
        rule_frame = replay[replay.index >= visible_since].copy()
        rule_switches = tuple(item for item in switches if _stamp(item.at) >= visible_since)
        if rule_frame.empty:
            st.caption("Ingen datapunkter i valgt testvindu.")
            return
        ai_full, ai_events_full = _ai_variant(replay, switches, reflections)
        ai_frame = ai_full[ai_full.index >= visible_since].copy()
        ai_events = tuple(item for item in ai_events_full if _stamp(item["at"]) >= visible_since)
        rule_summary = summarize_macd_supervisor_frame_v1(rule_frame, cost_bps_per_leg=cost_bps)
        ai_summary = summarize_macd_supervisor_frame_v1(ai_frame, cost_bps_per_leg=cost_bps)

        if RULE_NAME in visible_models:
            _render_metrics(RULE_NAME, rule_summary)
        if AI_NAME in visible_models:
            _render_metrics(AI_NAME, ai_summary)
            reflected_stamps = set(_reflection_by_stamp(reflections))
            covered = sum(1 for item in rule_switches if _stamp(item.at) in reflected_stamps)
            st.caption(f"AI-refleksjon finnes for {covered}/{len(rule_switches)} skift i valgt vindu. Resten følger regelmotoren inntil minnet er fylt.")

        st.plotly_chart(_figure(rule_frame, rule_switches, ai_events, visible_models), width="stretch", config={"displayModeBar":False})
        st.caption("Små piler viser regelmotoren; større piler viser AI-varianten.")

        with st.expander("Beslutninger · traverser skiftene", expanded=True):
            if not rule_switches:
                st.caption("Ingen skift i valgt vindu.")
                return
            nav_key = f"macd-supervisor-nav-{instrument_id}"
            st.session_state.setdefault(nav_key, len(rule_switches)-1)
            st.session_state[nav_key] = max(0, min(int(st.session_state[nav_key]), len(rule_switches)-1))
            left,right,label = st.columns([1,1,5])
            with left:
                if st.button("← Forrige", key=f"macd-supervisor-prev-{instrument_id}"):
                    st.session_state[nav_key] = max(0, int(st.session_state[nav_key])-1)
            with right:
                if st.button("Neste →", key=f"macd-supervisor-next-{instrument_id}"):
                    st.session_state[nav_key] = min(len(rule_switches)-1, int(st.session_state[nav_key])+1)
            selected = rule_switches[int(st.session_state[nav_key])]
            direction = "LONG" if selected.target > 0 else "SHORT"
            with label:
                st.markdown(f"**{int(st.session_state[nav_key])+1}/{len(rule_switches)} · regel {direction} · {selected.at.strftime('%Y-%m-%d %H:%M UTC')}**")
            st.write(selected.explanation)
            cols = st.columns(4)
            cols[0].metric("Total score", f"{selected.score:+.2f}")
            cols[1].metric("Confidence", f"{selected.confidence:.2f}")
            cols[2].metric("Slow context", f"{selected.context_score:+.2f}")
            cols[3].metric("Fast/mid change", f"{selected.change_score:+.2f}")

            reflection = _reflection_by_stamp(reflections).get(_stamp(selected.at))
            if reflection:
                target_word = {1:"LONG",0:"HOLD",-1:"SHORT"}[int(reflection["target"])]
                st.markdown(f"**AI-refleksjon · {target_word} · confidence {float(reflection['confidence']):.2f}**")
                st.write(reflection["summary"])
                st.caption(f"For: {reflection['supporting_case']}")
                st.caption(f"Mot: {reflection['counter_case']}")
                st.caption(f"Invalidering: {reflection['invalidation']}")
            else:
                st.info("AI-refleksjon er ikke lagret for dette skiftet ennå.")

            rows = [{"TF":f"{m}m","MACD spread":round(selected.spreads[m],6),"Δ spread":round(selected.slopes[m],6)} for m in (1,2,5,10,15,30)]
            st.dataframe(rows, width="stretch", hide_index=True)

        st.caption("Minne lagrer kompakte beslutningsepisoder og 5/15/30/60m-utfall; rå markedsdata dupliseres ikke.")

__all__=["render_tradingdesk_macd_supervisor_lab_v1"]
