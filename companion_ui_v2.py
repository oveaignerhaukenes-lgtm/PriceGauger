from __future__ import annotations

import html

import streamlit as st

from analyst_companion_v2 import derive_level_candidates_v2
from companion_runtime_v2 import CompanionSessionV2, ask_companion_v2, refresh_companion_session_v2
from config import openai_api_key, openai_companion_model
from openai_companion_provider import OpenAICompanionProviderV2
from ta_scenario_visualization_v2 import TA_SCENARIO_CSS, render_ta_scenario_chart_v2
from time_display_v2 import oslo_label


SESSION_KEY = "pg-v2-analyst-companion-session"
ENABLED_KEY = "pg-v2-ta-analyst-enabled"
MODE_KEY = "pg-v2-ta-analyst-mode"
QUESTION_KEY = "pg-v2-ta-analyst-question"
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


def _analysis_timeline_markup(session: CompanionSessionV2) -> str:
    cards: list[str] = []
    for item in session.analysis_history:
        scenario = item.scenarios[0] if item.scenarios else None
        scenario_text = ""
        if scenario is not None:
            scenario_text = f"<div class='pg-ta-history-scenario'>{html.escape(scenario.label)} · {scenario.probability:.0%}</div>"
        cards.append(
            "<div class='pg-ta-history-card'>"
            f"<div class='pg-ta-history-time'>{html.escape(oslo_label(item.as_of, include_date=False))}</div>"
            f"<div class='pg-ta-history-direction'>{html.escape(item.directional_context)}</div>"
            f"<div class='pg-ta-history-confidence'>AI confidence {item.confidence:.0%}</div>"
            f"{scenario_text}"
            "</div>"
        )
    return (
        "<style>"
        ".pg-ta-history-strip{display:flex;gap:.55rem;overflow-x:auto;padding:.15rem .05rem .65rem;scrollbar-width:thin;}"
        ".pg-ta-history-card{min-width:150px;max-width:190px;border:1px solid rgba(148,163,184,.25);border-radius:.65rem;"
        "padding:.6rem .7rem;background:rgba(15,23,42,.24);flex:0 0 auto;}"
        ".pg-ta-history-time{font-size:.78rem;color:#94a3b8}.pg-ta-history-direction{font-weight:700;margin-top:.2rem;}"
        ".pg-ta-history-confidence,.pg-ta-history-scenario{font-size:.78rem;color:#cbd5e1;margin-top:.15rem;}"
        "</style>"
        "<div class='pg-ta-history-strip'>" + "".join(cards) + "</div>"
    )


def _render_historical_analysis(session: CompanionSessionV2) -> None:
    if len(session.analysis_history) < 2:
        return
    labels = [oslo_label(item.as_of) for item in session.analysis_history]
    selected = st.select_slider(
        "Spol i TA-vurderinger",
        options=list(range(len(labels))),
        value=len(labels) - 1,
        format_func=lambda index: labels[index],
        key=f"pg-ta-history-selector:{session.session_id}",
        help="Sessionhistorikk. Nyeste vurdering står lengst til høyre; eldre vurderinger kan inspiseres uten å endre markedet.",
    )
    if selected == len(labels) - 1:
        return
    item = session.analysis_history[selected]
    with st.container(border=True):
        st.caption(f"Historisk TA-vurdering · {oslo_label(item.as_of)}")
        st.markdown(f"**{item.directional_context} · confidence {item.confidence:.0%}**")
        st.write(item.commentary)
        if item.what_changed:
            st.caption(f"Endring: {item.what_changed}")
        for scenario in item.scenarios:
            st.caption(f"{scenario.label} · {scenario.probability:.0%} · terminal {scenario.terminal_return * 100:+.3f}%")


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
            st.caption(f"Ny TA-vurdering · {oslo_label(view.as_of)} · {MODE_LABELS[session.activity_mode]}")
    except Exception as exc:
        st.warning(f"TA Analyst-oppdatering feilet: {exc}")

    analysis = session.analysis
    if analysis is None:
        st.info("TA Analyst venter på første gyldige analyse.")
        return

    with st.container(border=True):
        top_left, top_right = st.columns([3, 1])
        with top_left:
            st.markdown(f"**{html.escape(session.market)} · {MODE_LABELS[session.activity_mode]}**")
            st.caption(f"Vurdering fra {oslo_label(analysis.as_of)}")
        with top_right:
            st.caption(f"AI confidence {analysis.confidence:.0%}")

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

    if session.analysis_history:
        st.caption("TA-tidslinje · eldre vurderinger til venstre, nyeste til høyre")
        st.markdown(_analysis_timeline_markup(session), unsafe_allow_html=True)
        _render_historical_analysis(session)

    question = st.text_input(
        "Spør TA Analyst",
        placeholder="F.eks. normal pullback eller økende reversal-risk?",
        key=QUESTION_KEY,
    )
    if st.button("Spør", key=f"pg-v2-ta-ask:{view.market}"):
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
                st.caption(oslo_label(turn.as_of))
