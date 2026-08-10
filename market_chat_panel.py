from __future__ import annotations

from config import openai_api_key
from market_chat import answer_market_chat


def render_market_chat_panel(st, *, market: str) -> None:
    """Render one session-scoped conversation for the selected market.

    Conversation text stays in Streamlit session state. Authoritative market context
    is rebuilt from PostgreSQL inside ``answer_market_chat`` for every user turn.
    """
    market_name = str(market)
    st.subheader("Markedschat", divider="gray")
    st.caption(
        "Spør om markedet, scenarier, drivere, risiko eller hva som kan endre vurderingen. "
        "Hvert svar får fersk lagret PriceGauger-kontekst: pris, forecasts/læring, motorvekter, "
        "teknisk state, nyhetskontekst, historiske signaler og relevante Telegram-hendelser."
    )

    key = f"market-chat-messages:{market_name}"
    if key not in st.session_state:
        st.session_state[key] = []
    messages = st.session_state[key]

    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.caption(f"Samtalen gjelder **{market_name}**. Faktagrunnlaget bygges på nytt ved hvert spørsmål.")
    with top_right:
        if st.button("Nullstill", key=f"market-chat-clear:{market_name}", use_container_width=True):
            st.session_state[key] = []
            st.rerun()

    if not openai_api_key():
        st.info("OPENAI_API_KEY mangler i web-tjenesten; Markedschat kan ikke svare ennå.")
        return

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input(
        f"Spør om {market_name} …",
        key=f"market-chat-input:{market_name}",
    )
    if not prompt:
        return

    user_message = {"role": "user", "content": str(prompt)}
    messages.append(user_message)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Leser fersk PriceGauger-kontekst …"):
            try:
                answer = answer_market_chat(market_name, messages)
            except Exception as exc:
                st.error(f"Markedschat kunne ikke svare: {exc}")
                return
        st.markdown(answer)
    messages.append({"role": "assistant", "content": answer})
