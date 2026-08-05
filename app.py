from __future__ import annotations

import streamlit as st


overview = st.Page(
    "pages/0_Oversikt.py",
    title="Oversikt",
    icon="📡",
    default=True,
)

saxo = st.Page("pages/1_Saxo_OpenAPI.py", title="Saxo", icon="🔌")

system_pages = [
    st.Page("pages/Worker_Status.py", title="Workerstatus", icon="⚙️"),
    st.Page("pages/99_Runtime_Diagnostics.py", title="Runtime-diagnostikk", icon="🩺"),
    st.Page("pages/Signal_History.py", title="Signal-/outcomehistorikk", icon="🗂️"),
]

analysis_pages = [
    st.Page("pages/1_Kjerneflyt.py", title="Kjerneflyt", icon="🔁"),
    st.Page("pages/2_Direct_Technical.py", title="Teknisk analyse", icon="📈"),
    st.Page("pages/3_News_Context.py", title="Nyhetskontekst", icon="🌐"),
    st.Page("pages/4_Telegram_Flow.py", title="Telegram Flow", icon="🛰️"),
    st.Page("pages/5_AI_Market_Assessment.py", title="AI-markedsvurdering", icon="🤖"),
]

reference_pages = [
    st.Page("pages/0_Alpha_Lab.py", title="Alpha-lab (gammel)", icon="🧪"),
    st.Page("pages/1_Historical_Event_Lab.py", title="Historical Event Lab (gammel)", icon="🧬"),
    st.Page("pages/2_Signalaggregat.py", title="Signalaggregat (gammel)", icon="🧮"),
    st.Page("pages/Market_State.py", title="Market State", icon="🧭"),
]

navigation = st.navigation(
    {
        "PriceGauger": [overview, saxo],
        "System": system_pages,
        "Analyseverksted": analysis_pages,
        "Referansearkiv": reference_pages,
    }
)
navigation.run()
