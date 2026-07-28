from __future__ import annotations

import json
from typing import Any

import streamlit as st

from ai_market_assessment import assess_market
from engine_sidebar import render_engine_sidebar
from historical_engine import build_historical_assessment
from semantic_analogue_ranking import select_reactions_for_ranked_analogues
from telegram_gdelt_presenter import latest_result_summary


st.set_page_config(page_title="PriceGauger AI-vurdering", page_icon="🧠", layout="wide")
render_engine_sidebar(active="ai_assessment")
st.title("🧠 AI-markedsvurdering · v1")
st.caption(
    "Bygger en testbar kausal hypotese fra hendelsen, semantiske analoger, historisk kalibrering "
    "og siste tilgjengelige tekniske analyse. Historikken er støtte, ikke fasit."
)


def _technical_record() -> dict[str, Any] | None:
    candidates: list[tuple[str, Any]] = []
    for key in st.session_state:
        if str(key).startswith("direct_technical_Brent_"):
            candidates.append((str(key), st.session_state[key]))
    if not candidates:
        return None
    _, value = sorted(candidates, key=lambda item: item[0])[-1]
    regime = value.get("regime") if isinstance(value, dict) else None
    snapshots = value.get("snapshots") if isinstance(value, dict) else None
    if regime is None:
        return None
    return {
        "bias": getattr(regime, "bias", None),
        "regime": getattr(regime, "regime", None),
        "signal_quality": getattr(regime, "signal_quality", None),
        "reversal_risk": getattr(regime, "reversal_risk", None),
        "rationale": list(getattr(regime, "rationale", ()) or ()),
        "snapshots": {
            timeframe: {
                "price": getattr(snapshot, "price", None),
                "rsi_14": getattr(snapshot, "rsi_14", None),
                "macd_histogram": getattr(snapshot, "macd_histogram", None),
                "atr_14_pct": getattr(snapshot, "atr_14_pct", None),
                "readings": [getattr(item, "display", str(item)) for item in getattr(snapshot, "readings", ())],
            }
            for timeframe, snapshot in (snapshots or {}).items()
        },
    }


result = st.session_state.get("latest_telegram_gdelt_result")
semantic_rows = st.session_state.get("latest_semantic_analogue_ranking", [])
reaction_rows = st.session_state.get("latest_saxo_brent_reactions", [])

if result is None:
    st.warning("Kjør Historisk motor først slik at en aktuell Telegram-hendelse er tilgjengelig.")
else:
    summary = latest_result_summary(result)
    st.markdown("### Aktuell hendelse")
    st.write(summary["message_text"])

    historical_record = None
    selected_count = 0
    if semantic_rows and reaction_rows:
        selection = select_reactions_for_ranked_analogues(reaction_rows, semantic_rows)
        selected_count = selection.selected_count
        if selected_count:
            historical = build_historical_assessment(
                selection.selected_reactions,
                source_search_id=summary["search_id"],
                asset="Brent",
                semantic_filter_applied=True,
            )
            historical_record = historical.to_record()

    technical_record = _technical_record()
    c1, c2, c3 = st.columns(3)
    c1.metric("Semantiske analoger", len(semantic_rows))
    c2.metric("Valgte historiske analoger", selected_count)
    c3.metric("Teknisk analyse", "Tilgjengelig" if technical_record else "Mangler")

    if technical_record is None:
        st.info("Kjør Teknisk motor for Brent først for å gi AI-vurderingen oppdatert pris- og indikatorgrunnlag.")
    if historical_record is None:
        st.info("Historisk støtte mangler eller ingen analoger bestod filteret. AI-en kan fortsatt vurdere hendelsen, men må markere dette som usikkerhet.")

    if st.button("Lag testbar AI-vurdering", type="primary", use_container_width=True):
        event = {
            "message_text": summary["message_text"],
            "published_at": result.plan.published_at,
            "event_type": summary["event_type"],
            "actor": summary["actor"],
            "target": summary["target"],
            "country": summary["country"],
            "market_channel": summary["market_channel"],
            "interpretation_confidence": summary["interpretation_confidence"],
        }
        try:
            with st.spinner("Bygger kausal hypotese og testbar prisvurdering …"):
                assessment = assess_market(
                    instrument="Brent",
                    event=event,
                    historical=historical_record,
                    semantic_analogues=list(semantic_rows),
                    technical=technical_record,
                )
            st.session_state["latest_ai_market_assessment"] = assessment.to_record()
        except Exception as exc:
            st.error(f"AI-markedsvurderingen kunne ikke fullføres: {exc}")

    record = st.session_state.get("latest_ai_market_assessment")
    if record:
        st.markdown("### Testbar prognose")
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                st.caption(f"Retning · {record['primary_horizon']}")
                st.markdown(f"## {record['direction']}")
                st.write(
                    f"Opp: **{record['probability_up'] * 100:.0f} %** · "
                    f"ned: **{record['probability_down'] * 100:.0f} %**"
                )
        with right:
            with st.container(border=True):
                st.caption("Forventet intervall")
                st.markdown(
                    f"## {record['expected_move_low_pct']:+.2f} til "
                    f"{record['expected_move_high_pct']:+.2f} %"
                )
                st.write(f"Confidence: **{record['confidence'] * 100:.0f} %**")

        st.markdown("#### Kausal tese")
        st.write(record["causal_thesis"])
        st.markdown("#### Hva som allerede ser priset inn")
        st.write(record["already_priced_assessment"])
        st.markdown("#### Historisk støtte")
        st.write(record["historical_support"])
        st.markdown("#### Teknisk bekreftelse")
        st.write(record["technical_confirmation"])

        a, b = st.columns(2)
        with a:
            with st.container(border=True):
                st.markdown("**Ugyldiggjøring**")
                for item in record["invalidation_conditions"]:
                    st.write(f"- {item}")
        with b:
            with st.container(border=True):
                st.markdown("**Viktigste usikkerheter**")
                for item in record["key_uncertainties"]:
                    st.write(f"- {item}")

        with st.expander("Evidens og strukturert output"):
            for item in record["evidence"]:
                st.write(f"- {item}")
            st.json(record)
            st.download_button(
                "Last ned AI-vurdering som JSON",
                data=json.dumps(record, ensure_ascii=False, indent=2),
                file_name="ai_market_assessment_brent.json",
                mime="application/json",
                use_container_width=True,
            )
