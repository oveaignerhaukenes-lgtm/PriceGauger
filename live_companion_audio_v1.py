from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components


SESSION_KEY = "pg-v2-analyst-companion-session"
VOICE_ENABLED_KEY = "pg-live-companion-voice-enabled"
VOICE_ONLY_CHANGES_KEY = "pg-live-companion-voice-only-changes"
LAST_SPOKEN_KEY = "pg-live-companion-last-spoken"
GOLD_ENABLED_KEY = "pg-live-companion-market-gold"
SILVER_ENABLED_KEY = "pg-live-companion-market-silver"

_MARKET_TOGGLE_KEYS = {
    "Gold": GOLD_ENABLED_KEY,
    "Silver": SILVER_ENABLED_KEY,
}


def _session():
    return st.session_state.get(SESSION_KEY)


def _speech_key(session) -> str:
    analysis = session.analysis
    return f"{session.market}|{analysis.as_of.isoformat()}|{analysis.what_changed or ''}"


def _spoken_text(session, *, initial: bool = False) -> str:
    analysis = session.analysis
    parts: list[str] = [str(session.market)]

    if analysis.what_changed:
        parts.append(f"Endring: {analysis.what_changed}")
    elif initial:
        parts.append(f"{analysis.directional_context}. {analysis.commentary}")
    else:
        return ""

    if analysis.watch_conditions:
        parts.append("Følg med på: " + "; ".join(analysis.watch_conditions[:2]))

    cleaned = [str(part).strip().rstrip(".") for part in parts if str(part).strip()]
    return ". ".join(cleaned).strip()[:700]


def _market_enabled(market: str) -> bool:
    key = _MARKET_TOGGLE_KEYS.get(str(market))
    if key is None:
        return False
    return bool(st.session_state.get(key, False))


def _speak(text: str, *, interrupt: bool = False) -> None:
    payload = json.dumps(text, ensure_ascii=False)
    interrupt_js = "synth.cancel();" if interrupt else ""
    components.html(
        f"""
        <script>
        (() => {{
          const text = {payload};
          const synth = window.speechSynthesis;
          if (!synth || !text) return;
          {interrupt_js}
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = "nb-NO";
          utterance.rate = 1.0;
          const speak = () => {{
            const voices = synth.getVoices();
            const voice = voices.find(v => (v.lang || "").toLowerCase().startsWith("nb"))
              || voices.find(v => (v.lang || "").toLowerCase().startsWith("no"))
              || voices.find(v => (v.lang || "").toLowerCase().includes("nor"));
            if (voice) utterance.voice = voice;
            synth.speak(utterance);
          }};
          if (synth.getVoices().length) speak();
          else {{
            synth.onvoiceschanged = () => {{
              synth.onvoiceschanged = null;
              speak();
            }};
          }}
        }})();
        </script>
        """,
        height=0,
    )


def render_live_companion_audio_v1() -> None:
    """Render the first eyes-free output surface for the active TA Companion session."""
    st.markdown("#### Live Companion")
    st.caption("Velg markedene Companion skal få lov til å lese opp. Gull og sølv er første versjon; flere kan legges til senere.")

    if VOICE_ENABLED_KEY not in st.session_state:
        st.session_state[VOICE_ENABLED_KEY] = False
    if VOICE_ONLY_CHANGES_KEY not in st.session_state:
        st.session_state[VOICE_ONLY_CHANGES_KEY] = True
    if GOLD_ENABLED_KEY not in st.session_state:
        st.session_state[GOLD_ENABLED_KEY] = True
    if SILVER_ENABLED_KEY not in st.session_state:
        st.session_state[SILVER_ENABLED_KEY] = True

    market_controls = st.columns(2)
    with market_controls[0]:
        st.toggle("Gull", key=GOLD_ENABLED_KEY)
    with market_controls[1]:
        st.toggle("Sølv", key=SILVER_ENABLED_KEY)

    controls = st.columns([1, 1, 1])
    with controls[0]:
        enabled = st.toggle("Headset / tale", key=VOICE_ENABLED_KEY)
    with controls[1]:
        only_changes = st.toggle(
            "Kun endringer",
            key=VOICE_ONLY_CHANGES_KEY,
            disabled=not enabled,
            help="Når på leses bare nye materielle TA-endringer opp, ikke hvert snapshot.",
        )
    with controls[2]:
        test_audio = st.button("Test lyd", disabled=not enabled, key="pg-live-companion-test-audio")

    if test_audio:
        _speak("PriceGauger Live Companion er koblet til.", interrupt=True)
        st.success("Testmelding sendt til nettleserens taleutgang.")

    if not enabled:
        st.caption("Tale er av. TA Analyst fortsetter som før.")
        return

    selected_markets = [name for name, key in _MARKET_TOGGLE_KEYS.items() if bool(st.session_state.get(key, False))]
    if not selected_markets:
        st.caption("Ingen markeder er valgt for tale.")
        return

    session = _session()
    if session is None or not getattr(session, "active", False) or getattr(session, "analysis", None) is None:
        st.caption("Venter på aktiv TA Analyst og første analyse.")
        return

    if not _market_enabled(str(session.market)):
        st.caption(f"{session.market} er slått av for tale · valgt: {', '.join(selected_markets)}.")
        return

    key = _speech_key(session)
    last_key = st.session_state.get(LAST_SPOKEN_KEY)
    initial = not bool(last_key)

    if key == last_key:
        st.caption(f"Lytter til {session.market} · venter på neste TA-endring.")
        return

    text = _spoken_text(session, initial=initial or not only_changes)
    # Mark the snapshot handled even if it was intentionally silent, so rerenders cannot replay it.
    st.session_state[LAST_SPOKEN_KEY] = key

    if text:
        _speak(text)
        st.caption(f"Siste tale: {text}")
    else:
        st.caption(f"Lytter til {session.market} · nytt snapshot, ingen materiell endring å lese opp.")
