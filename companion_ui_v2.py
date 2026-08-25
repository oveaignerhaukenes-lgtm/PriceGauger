from __future__ import annotations

import html

import streamlit as st

from analyst_companion_v2 import derive_level_candidates_v2
from companion_runtime_v2 import CompanionSessionV2, ask_companion_v2, refresh_companion_session_v2
from config import openai_api_key, openai_companion_model
from openai_companion_provider import OpenAICompanionProviderV2
from ta_scenario_visualization_v2 import TA_SCENARIO_CSS, render_ta_scenario_chart_v2


SESSION_KEY = "pg-v2-analyst-companion-session"
ENABLED_KEY = "pg-v2-ta-analyst-enabled"
MODE_KEY = "pg-v2-ta-analyst-mode"
MODE_LABELS = {
    "QUIET": "Rolig",
    "NORMAL": "Normal",
    "ACTIVE": "Aktiv",
}


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
        parts.append("Støtte: " + ", ".join(f"{item.price:g} ({item.level_id})" for item in supports))
    if resistances:
        parts.append("Motstand: " + ", ".join(f"{item.price:g} ({item.level_id})" for item in resistances))
    return " · ".join(parts)


def render_companion_panel_v2(view) -> None:
    """Render the practical, technical-only TA Analyst for the active market."""
    st.markdown(TA_SCENARIO_CSS, unsafe_allow_html=True)
    st.divider()
    st.subheader("TA Analyst")
    st.caption(
        "Leser bare chart/Technical Core og følger markedet du har valgt. Ingen nyheter, Bias, posisjon eller execution inngår."
    )

    has_key = bool(openai_api_key())
    if ENABLED_KEY not in st.session_state:
        st.session_state[ENABLED_KEY] = False
    if MODE_KEY not in st.session_state:
        st.session_state[MODE_KEY] = "NORMAL"

    controls = st.columns([1, 2])
    with controls[0]:
        enabled = st.toggle(
            "TA Analyst på",
            key=ENABLED_KEY,
            disabled=not has_key,
            help="Aktiver løpende teknisk chart-lesning for valgt marked.",
        )
    with controls[1]:
        activity_mode = st.select_slider(
            "Følsomhet",
            options=("QUIET", "NORMAL", "ACTIVE"),
            value=st.session_state[MODE_KEY],
            format_func=lambda value: MODE_LABELS[value],
            key=MODE_KEY,
            disabled=not enabled,
            help=(
                "Rolig viser hovedsakelig regimeskifte, breakout og tydelig reversal. Normal tar også med momentum, "
                "exhaustion og retest. Aktiv viser tidligere, mer usikre tekniske varsler."
            ),
        )

    if not has_key:
        st.info("OPENAI_API_KEY må være konfigurert før TA Analyst kan aktiveres.")
        return

    session = _session()
    if not enabled:
        if session is not None and session.active:
            session.end()
        st.caption("TA Analyst er av. Forecast og Technical Core fortsetter uavhengig.")
        return

    # Practical use follows the market selector. A market switch starts a fresh,
    # blind technical session and never carries interpretation across instruments.
    if session is None or not session.active or session.market != str(view.market):
        session = CompanionSessionV2.activate(str(view.market), activity_mode=activity_mode)
        st.session_state[SESSION_KEY] = session
        force_refresh = True
    else:
        force_refresh = session.set_activity_mode(activity_mode)

    try:
        refreshed = refresh_companion_session_v2(
            session,
            view=view,
            provider=_provider(),
            force=force_refresh,
        )
        if refreshed:
            st.caption(f"Oppdatert fra Technical Core · {view.as_of} · {MODE_LABELS[session.activity_mode]}")
    except Exception as exc:
        st.warning(f"TA Analyst-oppdatering feilet: {exc}")

    analysis = session.analysis
    if analysis is None:
        st.info("TA Analyst venter på første gyldige analyse.")
        return

    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.markdown(f"**{html.escape(session.market)} · {MODE_LABELS[session.activity_mode]}**")
    with top_right:
        st.caption(f"confidence {analysis.confidence:.0%}")

    metrics = st.columns(4)
    metrics[0].metric("Retning", analysis.directional_context)
    metrics[1].metric("Breakout", analysis.breakout_status)
    metrics[2].metric("Pullback", analysis.pullback_type)
    metrics[3].metric("Squeeze", analysis.squeeze_risk)

    scenario_chart = render_ta_scenario_chart_v2(view, analysis)
    if scenario_chart:
        st.markdown(scenario_chart, unsafe_allow_html=True)
        st.caption(
            "Scenarioene er strukturert LLM-tolkning av den tekniske inputen. Den enkle deterministiske v2-prognosen over beholdes som baseline/benchmark."
        )
        with st.expander("Scenario-grunnlag", expanded=False):
            for scenario in analysis.scenarios:
                st.markdown(f"**{scenario.label} · {scenario.probability:.0%}**")
                st.write(scenario.rationale)
                st.caption(
                    f"Terminal {scenario.terminal_return * 100:+.3f}% · intervall {scenario.lower_return * 100:+.3f}% … {scenario.upper_return * 100:+.3f}% · invalidasjon: {scenario.invalidation}"
                )

    st.write(analysis.commentary)
    if analysis.what_changed:
        st.caption(f"Endring: {analysis.what_changed}")
    levels = _level_text(view, analysis)
    if levels:
        st.caption(levels)

    if analysis.watch_conditions:
        st.markdown("**Følg med på:**")
        for condition in analysis.watch_conditions:
            st.markdown(f"- {condition}")

    with st.form(f"ask-ta-analyst-form:{view.market}", clear_on_submit=True):
        question = st.text_input(
            "Spør TA Analyst",
            placeholder="F.eks. normal pullback eller økende reversal-risk?",
        )
        submitted = st.form_submit_button("Spør")
    if submitted:
        try:
            answer, confidence = ask_companion_v2(
                session,
                view=view,
                provider=_provider(),
                question=question,
            )
        except Exception as exc:
            st.warning(f"TA Analyst kunne ikke svare: {exc}")
        else:
            st.markdown(f"**TA Analyst:** {answer}")
            st.caption(f"Svar-confidence: {confidence:.0%}")

    recent_answers = [turn for turn in session.turns if turn.kind == "answer"][-3:]
    if recent_answers:
        with st.expander("Siste TA-svar"):
            for turn in reversed(recent_answers):
                st.write(turn.text)
                st.caption(turn.as_of)