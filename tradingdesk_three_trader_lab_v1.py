from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from autotrader_ai_baseline_v1 import STRATEGY_KEY as HOLISTIC_AI_STRATEGY_KEY
from autotrader_hybrid_replay_v1 import replay_hybrid_models_v1
from autotrader_macd_supervisor_normalized_replay_v1 import replay_normalized_macd_supervisor_v1
from autotrader_macd_supervisor_replay_v1 import replay_macd_supervisor_v1, summarize_macd_supervisor_frame_v1
from autotrader_position_manager_replay_v1 import apply_position_manager_v1
from autotrader_price_stoch_v1 import replay_price_stoch_v1
from autotrader_family_replay_v1 import replay_strategy_family_v1
from autotrader_strategy_family_v1 import family_display_label_v1
from autotrader_take_profit_modifier_v1 import apply_take_profit_replay_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_ui.charts.lightweight.three_trader_tv_v1 import render_three_trader_tv_v1
from tradingdesk_strategy_family_ui_v1 import load_sim_family_selection_v1

RULE_NAME = "Dum MACD"
ADAPTIVE_NAME = "MACD-adaptiv"
HOLISTIC_NAME = "Holistisk AI"
MANAGED_NAME = "MACD + manager"
NORMALIZED_NAME = "MACD norm"
NORMALIZED_MANAGED_NAME = "MACD norm + manager"
PRICE_STOCH_NAME = "Price + Stoch"
TAKE_PROFIT_NAME = "X + TakeProfit"
FAMILY_SIM_NAME = "Familie SIM"
ALL_MODELS = (
    RULE_NAME,
    ADAPTIVE_NAME,
    HOLISTIC_NAME,
    MANAGED_NAME,
    NORMALIZED_NAME,
    NORMALIZED_MANAGED_NAME,
    PRICE_STOCH_NAME,
    TAKE_PROFIT_NAME,
    FAMILY_SIM_NAME,
)


def _stamp(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _load_holistic_decisions(instrument_id: int, start: datetime, end: datetime) -> tuple[dict, ...]:
    try:
        with connect() as db:
            rows = db.execute(
                "SELECT action_at, price, target_direction, confidence, summary FROM pg_v2_autotrader_ai_baseline_samples WHERE strategy_key = ? AND instrument_id = ? AND action_at >= ? AND action_at <= ? ORDER BY action_at ASC",
                (HOLISTIC_AI_STRATEGY_KEY, int(instrument_id), start, end),
            ).fetchall()
    except Exception:
        return ()
    result = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0],
            "price": row[1],
            "target_direction": row[2],
            "confidence": row[3],
            "summary": row[4],
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
    ordered = sorted(decisions, key=lambda item: item["at"])
    current = cursor = 0
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


def _events_from_target(frame: pd.DataFrame, *, include_flat: bool = False) -> tuple[dict, ...]:
    events = []
    previous = 0
    for at, row in frame.iterrows():
        current = int(row["TARGET"])
        changed = current != previous
        visible_target = current in (-1, 1) or (include_flat and current == 0 and previous in (-1, 1))
        if changed and visible_target:
            events.append({"at": _stamp(at), "price": float(row["PRICE"]), "target": current})
        previous = current
    return tuple(events)


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
        st.markdown("### Strategier · samme marked")
        st.caption(
            "Samme canonical prisserie med signal-/manager-spor og PG Price + Stoch. "
            "Price + Stoch lar pris eie retningen; stochastic-vectoren varsler/kan gå FLAT tidlig, "
            "men får ikke reversere uten prisbekreftelse."
        )
        family_sim_selection = load_sim_family_selection_v1(int(instrument_id))
        controls = st.columns([1, 1, 2])
        with controls[0]:
            hours = int(st.selectbox(
                "Vindu",
                (6, 12, 24, 48),
                index=2,
                format_func=lambda value: f"{value} t",
                key=f"three-trader-window-{instrument_id}",
            ))
        with controls[1]:
            cost_bps = float(st.number_input(
                "Kostnad / ordrebein (bps)",
                0.0,
                25.0,
                0.0,
                0.1,
                key=f"three-trader-cost-{instrument_id}",
            ))
        with controls[2]:
            visible = st.multiselect(
                "Vis / plott",
                ALL_MODELS,
                default=ALL_MODELS,
                key=f"three-trader-visible-{instrument_id}",
            )

        tp_controls = st.columns([2, 1, 1])
        with tp_controls[0]:
            tp_base_options = tuple(
                item for item in ALL_MODELS
                if item != TAKE_PROFIT_NAME
                and (item != FAMILY_SIM_NAME or family_sim_selection is not None)
            )
            tp_base = st.selectbox(
                "TakeProfit base (X)",
                tp_base_options,
                index=6,
                key=f"three-trader-tp-base-{instrument_id}",
            )
        with tp_controls[1]:
            tp_giveback = float(st.number_input(
                "TP giveback (%)",
                min_value=1.0,
                max_value=95.0,
                value=10.0,
                step=1.0,
                key=f"three-trader-tp-giveback-{instrument_id}",
            ))
        with tp_controls[2]:
            tp_min_peak = float(st.number_input(
                "TP arm ≥ (%)",
                min_value=0.0,
                max_value=100.0,
                value=0.10,
                step=0.05,
                format="%.2f",
                key=f"three-trader-tp-arm-{instrument_id}",
            ))

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours + 18)
        try:
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=int(instrument_id),
                start=start,
                end=end,
                limit=12000,
            )
            rule_full, rule_switches, _ = replay_macd_supervisor_v1(bars, cost_bps_per_leg=cost_bps)
            adaptive_full, _ = replay_hybrid_models_v1(bars, cost_bps_per_leg=cost_bps)
            managed_full = apply_position_manager_v1(
                rule_full[["PRICE", "TARGET", "AUTHORITATIVE_CROSS"]]
            )
            normalized_full, normalized_switches, _ = replay_normalized_macd_supervisor_v1(
                bars,
                cost_bps_per_leg=cost_bps,
            )
            normalized_managed_full = apply_position_manager_v1(
                normalized_full[["PRICE", "TARGET", "AUTHORITATIVE_CROSS"]]
            )
            price_stoch_full = replay_price_stoch_v1(bars)
            family_sim_full = (
                replay_strategy_family_v1(
                    bars,
                    family=family_sim_selection.family,
                    timeframe_minutes=family_sim_selection.timeframe_minutes,
                )
                if family_sim_selection is not None
                else None
            )
        except Exception as exc:
            st.caption(f"Trader-lab venter på nok canonical data: {exc}")
            return

        visible_since = _stamp(end - timedelta(hours=hours))
        rule_frame = rule_full[rule_full.index >= visible_since][["PRICE", "TARGET"]].copy()
        managed_frame = managed_full[managed_full.index >= visible_since][["PRICE", "TARGET"]].copy()
        normalized_frame = normalized_full[normalized_full.index >= visible_since][["PRICE", "TARGET"]].copy()
        normalized_managed_frame = normalized_managed_full[
            normalized_managed_full.index >= visible_since
        ][["PRICE", "TARGET"]].copy()
        price_stoch_frame = price_stoch_full[
            price_stoch_full.index >= visible_since
        ][["PRICE", "TARGET"]].copy()
        family_sim_frame = (
            family_sim_full[family_sim_full.index >= visible_since][["PRICE", "TARGET"]].copy()
            if family_sim_full is not None
            else None
        )

        adaptive_slice = adaptive_full[adaptive_full.index >= visible_since]
        adaptive_frame = pd.DataFrame(index=adaptive_slice.index)
        adaptive_frame["PRICE"] = adaptive_slice["PRICE"]
        adaptive_frame["TARGET"] = adaptive_slice["TARGET_MACD-A"]
        decisions = _load_holistic_decisions(int(instrument_id), end - timedelta(hours=hours), end)
        holistic_frame = _target_frame(rule_frame, decisions)

        base_frames = {
            RULE_NAME: rule_frame,
            ADAPTIVE_NAME: adaptive_frame,
            HOLISTIC_NAME: holistic_frame,
            MANAGED_NAME: managed_frame,
            NORMALIZED_NAME: normalized_frame,
            NORMALIZED_MANAGED_NAME: normalized_managed_frame,
            PRICE_STOCH_NAME: price_stoch_frame,
        }
        if family_sim_frame is not None:
            base_frames[FAMILY_SIM_NAME] = family_sim_frame
        take_profit_frame = apply_take_profit_replay_v1(
            base_frames[tp_base],
            giveback_pct=tp_giveback,
            min_peak_profit_pct=tp_min_peak,
        )

        rule_events = tuple(
            {"at": _stamp(item.at), "price": float(item.price), "target": int(item.target)}
            for item in rule_switches
            if _stamp(item.at) >= visible_since
        )
        normalized_events = tuple(
            {"at": _stamp(item.at), "price": float(item.price), "target": int(item.target)}
            for item in normalized_switches
            if _stamp(item.at) >= visible_since
        )
        adaptive_events = _events_from_target(adaptive_frame)
        holistic_events = tuple(item for item in decisions if int(item["target"]) in (-1, 1))
        managed_events = _events_from_target(managed_frame, include_flat=True)
        normalized_managed_events = _events_from_target(normalized_managed_frame, include_flat=True)
        price_stoch_events = _events_from_target(price_stoch_frame, include_flat=True)
        take_profit_events = _events_from_target(take_profit_frame, include_flat=True)
        family_sim_events = (
            _events_from_target(family_sim_frame, include_flat=True)
            if family_sim_frame is not None
            else ()
        )
        event_sets = {
            RULE_NAME: rule_events,
            ADAPTIVE_NAME: adaptive_events,
            HOLISTIC_NAME: holistic_events,
            MANAGED_NAME: managed_events,
            NORMALIZED_NAME: normalized_events,
            NORMALIZED_MANAGED_NAME: normalized_managed_events,
            PRICE_STOCH_NAME: price_stoch_events,
            TAKE_PROFIT_NAME: take_profit_events,
            FAMILY_SIM_NAME: family_sim_events,
        }

        if RULE_NAME in visible:
            _render_metrics(RULE_NAME, rule_frame, cost_bps=cost_bps)
        if MANAGED_NAME in visible:
            _render_metrics(MANAGED_NAME, managed_frame, cost_bps=cost_bps)
        if NORMALIZED_NAME in visible:
            _render_metrics(NORMALIZED_NAME, normalized_frame, cost_bps=cost_bps)
        if NORMALIZED_MANAGED_NAME in visible:
            _render_metrics(NORMALIZED_MANAGED_NAME, normalized_managed_frame, cost_bps=cost_bps)
        if PRICE_STOCH_NAME in visible:
            _render_metrics(PRICE_STOCH_NAME, price_stoch_frame, cost_bps=cost_bps)
        if TAKE_PROFIT_NAME in visible:
            _render_metrics(
                f"{tp_base} + TakeProfit {tp_giveback:.0f}%",
                take_profit_frame,
                cost_bps=cost_bps,
            )
        if FAMILY_SIM_NAME in visible:
            if family_sim_frame is not None and family_sim_selection is not None:
                _render_metrics(
                    f"SIM · {family_display_label_v1(family_sim_selection.family, family_sim_selection.timeframe_minutes)}",
                    family_sim_frame,
                    cost_bps=cost_bps,
                )
            else:
                st.markdown(f"**{FAMILY_SIM_NAME}**")
                st.caption("Velg SIM i strategifamilie-byggeren over for å legge et familiespor her.")
        if ADAPTIVE_NAME in visible:
            _render_metrics(ADAPTIVE_NAME, adaptive_frame, cost_bps=cost_bps)
        if HOLISTIC_NAME in visible:
            if decisions:
                _render_metrics(HOLISTIC_NAME, holistic_frame, cost_bps=cost_bps)
            else:
                st.markdown(f"**{HOLISTIC_NAME}**")
                st.caption("Ingen lagrede holistiske AI-beslutninger i valgt vindu ennå.")

        if MANAGED_NAME in visible or NORMALIZED_MANAGED_NAME in visible:
            st.caption(
                "Manager v1: 3-bar reversal-bekreftelse mellom signalene, volatilitetsarmert "
                "peak-profit-lock, maks 25% giveback fra MFE og kort re-entry cooldown. Bekreftet "
                "5m MACD-cross er autoritativt og bypasser reversal-delay. Sirkelmarkør = manager gikk FLAT."
            )
        if NORMALIZED_NAME in visible or NORMALIZED_MANAGED_NAME in visible:
            st.caption(
                "Norm v1: hver timeframe skaleres mot sin egen tidligere MACD-spread før vekting. "
                "Det fjerner rå skala-fordelen 15m/30m har over 1m/2m/5m, uten å endre live-strategien."
            )
        if PRICE_STOCH_NAME in visible:
            st.caption(
                "Price + Stoch: 1m price-vector er beslutningssignal. %K-slope over 1/3/5 bars er scout/halvparade; "
                "scouten kan gå FLAT når pris ikke lenger bekrefter aktiv retning, men kan ikke alene gå motsatt."
            )
        if TAKE_PROFIT_NAME in visible:
            st.caption(
                f"X + TakeProfit: base={tp_base}. Når peak-profit er minst {tp_min_peak:.2f}%, "
                f"går wrapperen FLAT etter {tp_giveback:.1f}% relativ giveback av peak-profit. "
                "Etter exit holder replayen FLAT til base-strategien faktisk skifter target."
            )

        if FAMILY_SIM_NAME in visible and family_sim_selection is not None:
            st.caption(
                "Familie SIM bruker samme familie/timeframe-policy som LIVE-builderen, "
                "men uten execution-authority."
            )

        render_three_trader_tv_v1(rule_frame, event_sets, visible, key=f"three-trader-chart-{instrument_id}")
        st.caption(
            "TV-chart: dra/pinch/zoom i grafen, dra håndtaket under for høyde. Visningsområde og høyde huskes. "
            "Markørene viser modellskiftene på samme prisserie; alle spor her er analyse-only."
        )


__all__ = ["render_tradingdesk_three_trader_lab_v1"]
