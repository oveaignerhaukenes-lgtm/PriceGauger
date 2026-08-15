from __future__ import annotations

import html

import streamlit as st

from analyst_companion_v2 import derive_level_candidates_v2
from companion_runtime_v2 import CompanionSessionV2, ask_companion_v2, refresh_companion_session_v2
from config import openai_api_key, openai_companion_model
from openai_companion_provider import OpenAICompanionProviderV2


SESSION_KEY = "pg-v2-analyst-companion-session"


def _provider() -> OpenAICompanionProviderV2:
    return OpenAICompanionProviderV2(
        api_key=openai_api_key(),
        model_version=openai_companion_model(),
    )


def _session() -> CompanionSessionV2 | None:
    value = st.session_state.get(SESSION_KEY)
    return value if isinstance(value, CompanionSessionV2) else None


def _level_text(view, analysis) -> str:
    candidates = {item.level_id: item for item in derive_level_candidates_v2(view.price_history)}
    parts: list[str] = []
    supports = [candidates.get(level_id) for level_id in analysis.watched_support_ids]
    resistances = [candidates.get(level_id) for level_id in analysis.watched_resistance_ids]
    supports = [item for item in supports if item is not None]
    resistances = [item for item in resistances if item is not None]
    if supports:
        parts.append("Support: " + ", ".join(f"{item.price:g} ({item.level_id})" for item in supports))
    if resistances:
        parts.append("Resistance: " + ", ".join(f"{item.price:g} ({item.level_id})" for item in resistances))
    return " · ".join(parts)


def render_companion_panel_v2(view) -> None:
    """Render one session-scoped, analysis-only Companion beside the live v2 chart."""
    st.divider()
    st.subheader("Analyst Companion")
    st.caption(
        "Session-basert teknisk analyse for markedet du følger. Companion kan analysere og svare på spørsmål, "
        "men har ingen ordre-, posisjons- eller AutoTrader-tilgang."
    )

    session = _session()
    has_key = bool(openai_api_key())

    if session is None or not session.active:
        if not has_key:
            st.info("OPENAI_API_KEY må være konfigurert før Companion kan aktiveres.")
            return
        if st.button("Activate Companion", type="primary", key=f"activate-companion:{view.market}"):
            session = CompanionSessionV2.activate(view.market)
            st.session_state[SESSION_KEY] = session
            try:
                refresh_companion_session_v2(session, view=view, provider=_provider(), force=True)
            except Exception as exc:
                st.warning(f"Companion kunne ikke starte analysen: {exc}")
            st.rerun()
        return

    if session.market != str(view.market):
        st.warning(
            f"Companion-sessionen følger {session.market}. Avslutt den før du aktiverer Companion for {view.market}."
        )
        if st.button("End session", key="end-companion-other-market"):
            session.end()
            st.rerun()
        return

    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.markdown(f"**Companion active · {html.escape(session.market)}**")
        st.caption(f"Session {session.session_id[:8]} · activated {session.activated_at}")
    with top_right:
        if st.button("End session", key=f"end-companion:{view.market}"):
            session.end()
            st.rerun()

    try:
        refreshed = refresh_companion_session_v2(session, view=view, provider=_provider())
        if refreshed:
            st.caption(f"Oppdatert fra nytt Technical Core-snapshot: {view.as_of}")
    except Exception as exc:
        st.warning(f"Companion-oppdatering feilet: {exc}")

    analysis = session.analysis
    if analysis is None:
        st.info("Companion venter på første gyldige analyse.")
        return

    metrics = st.columns(4)
    metrics[0].metric("Kontekst", analysis.directional_context)
    metrics[1].metric("Breakout", analysis.breakout_status)
    metrics[2].metric("Pullback", analysis.pullback_type)
    metrics[3].metric("Squeeze risk", analysis.squeeze_risk)

    st.write(analysis.commentary)
    if analysis.what_changed:
        st.caption(f"Endring: {analysis.what_changed}")
    levels = _level_text(view, analysis)
    if levels:
        st.caption(levels)
    st.caption(f"Companion confidence: {analysis.confidence:.0%}")

    if analysis.watch_conditions:
        st.markdown("**Følger nå:**")
        for condition in analysis.watch_conditions:
            st.markdown(f"- {condition}")

    with st.form(f"ask-companion-form:{view.market}", clear_on_submit=True):
        question = st.text_input(
            "Ask Companion",
            placeholder="F.eks. ser dette ut som en normal pullback eller økende reversal-risk?",
        )
        submitted = st.form_submit_button("Ask Companion")
    if submitted:
        try:
            answer, confidence = ask_companion_v2(
                session,
                view=view,
                provider=_provider(),
                question=question,
            )
        except Exception as exc:
            st.warning(f"Companion kunne ikke svare: {exc}")
        else:
            st.markdown(f"**Companion:** {answer}")
            st.caption(f"Svar-confidence: {confidence:.0%}")

    recent_answers = [turn for turn in session.turns if turn.kind == "answer"][-3:]
    if recent_answers:
        with st.expander("Recent Companion answers"):
            for turn in reversed(recent_answers):
                st.write(turn.text)
                st.caption(turn.as_of)
