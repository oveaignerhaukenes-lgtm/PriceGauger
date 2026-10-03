from __future__ import annotations

import streamlit as st


st.title("Skilled Money")
st.caption("Et read-only læringskart over hvem som flytter markedet, hvorfor de handler, og hvilke spor de kan etterlate.")

st.info(
    "Denne siden er bevisst frakoblet AutoTrader, execution og logging. "
    "Den skal forklare observerbare markedsmekanismer retrospektivt — ikke gi kjøp/salg-signaler eller prediksjoner."
)

st.subheader("Aktørkart")
actors = [
    ("CTA / trend", "Pris, momentum og volatilitet", "Systematiske trendregler", "Vedvarende retning, breakout/scale-in-flow"),
    ("Discretionary macro / hedgefond", "Makro, relative value, narrativ", "Avkastning / asymmetri", "Cross-asset reprising, rates/FX/indeks"),
    ("Optionsdealere / market makers", "Opsjonsbok, delta/gamma/vega", "Hedge inventory / spread", "Hedging-flow rundt strikes og vol-endringer"),
    ("Vol-control / risk parity", "Realisert vol, korrelasjon, risiko", "Målstyrt porteføljerisiko", "Mekanisk deleveraging/releveraging"),
    ("Pensjon / long-only", "Allokering, benchmark, liabilities", "Lang horisont / mandat", "Rebalansering og store langsomme flows"),
    ("Passive / ETF", "Indeksvekter og investor-flow", "Tracking", "Close/rebalance/index-event flow"),
    ("Corporate / hedgers", "Finansiering, råvarer, valuta", "Redusere virksomhetsrisiko", "Hedge-flow som ikke er retningssyn"),
    ("Sentralbank / offentlig sektor", "Reserver, valuta, likviditet", "Policy / reserveforvaltning", "FX-, rente-, gull- og likviditetseffekter"),
    ("Retail", "Pris, nyheter, sentiment", "Spekulasjon / investering", "Kan forsterke momentum, særlig i konsentrerte instrumenter"),
]

for name, observes, motive, footprint in actors:
    with st.expander(name):
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Ser på**\n\n{observes}")
        c2.markdown(f"**Motivasjon / constraint**\n\n{motive}")
        c3.markdown(f"**Mulig markedsavtrykk**\n\n{footprint}")

st.subheader("Fra hendelse til pris")
st.markdown(
    """
    **Verden / nyhet** → **hva var allerede priset inn?** → **hvilke aktører rammes?** →
    **hvilke constraints eller incentiver endres?** → **ordreflow** → **likviditet / market making** → **prisrespons**

    Poenget er å skille *betydningen av hendelsen* fra *mekanismen som faktisk produserer handler*.
    """
)

st.subheader("Tre lag å lese samtidig")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("### Teknisk regime")
    st.markdown("Trend · volatilitet · momentum · korrelasjon · likviditet · termstruktur")
with c2:
    st.markdown("### Verden / nyheter")
    st.markdown("Vekst · inflasjon · renter · energi · geopolitikk · selskaper · policy")
with c3:
    st.markdown("### Aktørregime")
    st.markdown("Hvem kan være marginal kjøper/selger, og hvilke regler eller constraints kan drive flowen?")

st.subheader("Retrospektiv forklaring")
st.caption("Arbeidsmal for å lære av en faktisk markedsbevegelse uten å late som aktøridentitet er direkte observert.")
with st.container(border=True):
    st.markdown(
        """
        1. **Hva skjedde?** Beskriv pris, volatilitet og cross-asset-respons først.  
        2. **Hva kom inn av informasjon?** Skill ny informasjon fra kjent/priset informasjon.  
        3. **Hvem hadde grunn til å handle?** Ranger plausible aktørmekanismer.  
        4. **Var handelen frivillig eller mekanisk?** Signal, hedge, rebalansering, margin/risiko eller policy.  
        5. **Hvilke observerbare spor støtter forklaringen?** Pris/volum, vol, rates, FX, optionsdata, flows, positioning.  
        6. **Hva vet vi ikke?** Hold inferens tydelig adskilt fra observerte data.
        """
    )

st.subheader("Visualiseringer å fylle med data")
left, right = st.columns(2)
with left:
    st.markdown("**Aktørtrykk**")
    st.progress(0, text="Ingen datakilde koblet — placeholder")
    st.caption("Senere: relative, evidensbaserte indikatorer for plausible flow-kilder. Ikke 'smart money score'.")
with right:
    st.markdown("**Mekanismekjede**")
    st.code("event → actor constraint → flow → liquidity → price", language=None)

st.markdown("**Regime × aktør-matrise**")
st.dataframe(
    {
        "Aktør": ["CTA", "Dealers", "Macro", "Vol-control", "Long-only"],
        "Trend": ["relevant", "indirekte", "relevant", "indirekte", "lav/moderat"],
        "Volatilitet": ["relevant", "svært relevant", "relevant", "svært relevant", "moderat"],
        "Makronyhet": ["via pris", "via vol/flow", "svært relevant", "via risiko", "relevant"],
        "Rebalansering": ["lav", "moderat", "moderat", "moderat", "svært relevant"],
    },
    use_container_width=True,
    hide_index=True,
)

st.warning(
    "Aktøraktivitet er ofte latent. Siden skal aldri presentere en bestemt aktør som årsak uten direkte evidens; "
    "ellers merkes forklaringen som inferens/hypotese."
)
