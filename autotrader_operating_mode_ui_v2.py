from __future__ import annotations

import streamlit as st


def render_operating_modes_v2() -> None:
    st.subheader("Operasjonsmodus")
    st.caption(
        "AutoTrader skal få to tydelig forskjellige mandat. Dette panelet beskriver authority-kontrakten som resten av "
        "execution-laget bygges mot; det åpner ikke ny LIVE-authority i seg selv."
    )

    auto, guardian = st.columns(2, gap="large")
    with auto:
        st.markdown("### AutoTrader")
        st.write("Velger og håndterer en posisjon innenfor eksplisitt PG Product Universe og hard Margin Envelope.")
        st.markdown("**Kan be om:** OPEN · ADD · REDUCE · CLOSE")
        st.caption(
            "Retningsskifte er alltid CLOSE → bekreftet FLAT → ny OPEN. Strategi/AI kan aldri endre margin-, notional- "
            "eller produktgrensene."
        )

    with guardian:
        st.markdown("### Position Guardian")
        st.write("Passer en allerede eid/enrollet posisjon når du ikke følger markedet selv.")
        st.markdown("**Standard:** HOLD · REDUCE · CLOSE")
        st.caption(
            "Ingen selvstendig entry eller ADD. En valgfri Protect + Flip-modus kan senere åpne motsatt retning bare "
            "etter at den opprinnelige managed-posisjonen er lukket og kontoen er bekreftet FLAT."
        )

    st.info(
        "Neste kobling er Technical Core → Position Guardian-policy. Først når den policyen er auditérbar kobles CLOSE/REDUCE "
        "til eksisterende execution-gates; autonom OPEN/ADD kommer separat bak Product Universe + Margin Envelope."
    )
