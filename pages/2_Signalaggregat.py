from __future__ import annotations

import pandas as pd
import streamlit as st

from build_info import render_build_badge
from decision_engine import build_strategy_suggestion
from signal_aggregator import build_aggregate_signal


st.set_page_config(page_title="PriceGauger Signalaggregat", page_icon="∑", layout="wide")
render_build_badge()

ASSETS = ("Brent", "Silver", "Gold", "DXY")

st.title("∑ Signalaggregat")
st.caption(
    "Hver hendelse analyseres separat mot egne historiske analoger. "
    "Først etterpå summeres hendelsessignalene til ett beslutningsgrunnlag."
)

with st.sidebar:
    st.header("Aggregat")
    asset = st.selectbox("Marked", ASSETS, key="aggregate_asset")
    window_hours = st.selectbox("Tidsvindu", (6, 12, 24), index=2, format_func=lambda value: f"{value} timer")
    half_life_hours = st.slider(
        "Halveringstid for nyhetsvekt",
        min_value=1.0,
        max_value=12.0,
        value=6.0,
        step=0.5,
        help="Et signal som er én halveringstid gammelt får halv tidsvekt.",
    )
    minimum_similarity = st.slider(
        "Minste analoglikhet",
        min_value=0.0,
        max_value=1.0,
        value=0.20,
        step=0.05,
    )
    profit_capture = st.slider("Andel av forventet bevegelse til autosalg", 0.50, 1.00, 0.80, 0.05)


events = st.session_state.get("gdelt_events", [])
reactions = st.session_state.get("gdelt_intraday_reactions", [])

if not events:
    st.info(
        "Ingen hendelser er lastet i denne økten. Kjør Historical Event Lab først, "
        "og åpne deretter Signalaggregat."
    )
    st.stop()

aggregate = build_aggregate_signal(
    events=events,
    reactions=reactions,
    asset=asset,
    window_hours=window_hours,
    half_life_hours=half_life_hours,
    minimum_similarity=minimum_similarity,
)
st.session_state["aggregate_signal"] = aggregate
st.session_state["aggregate_market_assessment"] = aggregate.to_market_assessment()

assessment = aggregate.to_market_assessment()
strategy = build_strategy_suggestion(assessment, profit_capture=profit_capture)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Aggregert retning", aggregate.direction)
m2.metric("Konfidens", f"{aggregate.confidence_pct:.1f} %")
m3.metric("Hendelser brukt", f"{aggregate.events_used}/{aggregate.events_considered}")
m4.metric(
    "Forventet bevegelse",
    f"{aggregate.expected_move_pct:+.3f} %" if aggregate.expected_move_pct is not None else "Mangler data",
)

s1, s2, s3, s4 = st.columns(4)
s1.metric("Netto signal", f"{aggregate.net_score:+.3f}")
s2.metric("Retningsenighet", f"{aggregate.agreement_pct:.1f} %")
s3.metric("Effektivt utvalg", f"{aggregate.effective_event_count:.2f}")
s4.metric("Evidensgrad", aggregate.evidence_grade)

with st.container(border=True):
    st.markdown("### Aggregert beslutningsgrunnlag")
    for line in aggregate.rationale:
        st.write(f"• {line}")

with st.container(border=True):
    st.markdown("### Output til beslutningslaget")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Handling", strategy.action)
    q2.metric("Maks gearing", f"{strategy.max_leverage:.1f}×")
    q3.metric("Autosalg", f"{strategy.take_profit_pct:.3f} %" if strategy.take_profit_pct is not None else "—")
    q4.metric("Stop", f"{strategy.stop_loss_pct:.3f} %" if strategy.stop_loss_pct is not None else "—")
    st.write(strategy.methodology)
    st.warning(strategy.warning)

st.markdown("### Bidrag fra enkelthendelser")
rows = []
for signal in aggregate.event_signals:
    rows.append(
        {
            "Publisert": signal.published_at,
            "Hendelse": signal.title,
            "Type": signal.event_type,
            "Mål": signal.target,
            "Retning": signal.direction,
            "Konfidens %": signal.confidence_pct,
            "Forventet %": signal.expected_move_pct,
            "Analogutvalg": signal.analogue_sample,
            "Effektivt analogutvalg": signal.effective_analogue_sample,
            "Alder timer": signal.age_hours,
            "Tidsvekt": signal.freshness_weight,
            "Signalvekt": signal.signal_weight,
            "Bidrag": signal.contribution,
            "Evidens": signal.evidence_grade,
        }
    )

frame = pd.DataFrame(rows)
if frame.empty:
    st.info(f"Ingen hendelser falt innenfor de siste {window_hours} timene.")
else:
    st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        column_config={
            "Publisert": st.column_config.DatetimeColumn("Publisert UTC"),
            "Konfidens %": st.column_config.NumberColumn("Konfidens", format="%.1f %%"),
            "Forventet %": st.column_config.NumberColumn("Forventet", format="%+.3f %%"),
            "Tidsvekt": st.column_config.NumberColumn("Tidsvekt", format="%.3f"),
            "Signalvekt": st.column_config.NumberColumn("Signalvekt", format="%.3f"),
            "Bidrag": st.column_config.NumberColumn("Netto bidrag", format="%+.3f"),
        },
    )
    st.download_button(
        "Last ned hendelsessignaler som CSV",
        frame.to_csv(index=False).encode("utf-8"),
        "event_signal_aggregate.csv",
        "text/csv",
        width="stretch",
    )

with st.expander("Se komplett aggregatobjekt"):
    st.json(aggregate.to_record())
