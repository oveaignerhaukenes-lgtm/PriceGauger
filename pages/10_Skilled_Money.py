from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st


st.title("Skilled Money")
st.caption("Retrospektiv læring: fra markedsbevegelse til aktører, constraints, ordreflow og senere bekreftelse.")
st.info(
    "Læringsflate, ikke trading-signal. AutoTrader og execution leser ikke denne siden. "
    "Første versjon bruker et demonstrasjonssnapshot slik at arbeidsformen kan vurderes før datakilder kobles på."
)

# A deliberately static worked example. It demonstrates the information model without
# pretending that we already have actor-identifying data or a production event detector.
example = {
    "title": "Eksempel · kraftig fall i US Tech 100",
    "move": "−2,1 % på 47 min",
    "status": "RETROSPEKTIV · DEMO",
    "initial": "Renter steg samtidig som tech falt. Makro/reprising er direkte observerbart; systematisk deleveraging er foreløpig bare en hypotese.",
    "later": "Senere positioning-/flowdata kan styrke, svekke eller avkrefte hypotesen. Den opprinnelige vurderingen beholdes uendret.",
}

st.subheader("Hendelsesjournal")
with st.container(border=True):
    a, b, c = st.columns([2, 1, 1])
    a.markdown(f"### {example['title']}")
    b.metric("Bevegelse", example["move"])
    c.metric("Status", example["status"])
    st.markdown("**T0 · hva kunne vi si da?**")
    st.write(example["initial"])
    st.markdown("**T+ · hva kan senere data endre?**")
    st.write(example["later"])

st.markdown("#### Evidensstabel")
evidence = pd.DataFrame(
    [
        ["Pris", "Tech falt raskt", "Observert", "Høy", "T0"],
        ["Rates", "Renter steg samtidig", "Observert", "Høy", "T0"],
        ["Volatilitet", "Volatilitet ekspanderte", "Observert", "Høy", "T0"],
        ["Macro funds", "Reprising kan ha bidratt", "Inferert", "Middels", "T0"],
        ["CTA / systematic", "Deleveraging kan ha forsterket bevegelsen", "Inferert", "Lav", "T0"],
        ["Leveraged funds", "Kan senere kontrolleres mot positioning", "Avventer data", "—", "T+ dager"],
    ],
    columns=["Lag", "Påstand", "Type", "Confidence", "Tilgjengelig"],
)
st.dataframe(evidence, use_container_width=True, hide_index=True)

st.markdown("#### Hvordan forklaringen modnes")
timeline = pd.DataFrame(
    {
        "Fase": ["T0", "T+1d", "T+1 uke", "T+uker"],
        "Typiske nye data": [
            "pris · volum · rates · FX · vol · nyheter",
            "options/OI · ETF/flow · dagsdata",
            "CFTC/COT · bredere positioning",
            "holdings · reserve-/fondrapporter · revisjoner",
        ],
        "Handling": [
            "opprett første forklaring",
            "legg til revisjon",
            "bekreft/svekk aktørhypoteser",
            "lukk eller behold usikker forklaring",
        ],
    }
)
st.dataframe(timeline, use_container_width=True, hide_index=True)

st.markdown("#### Mekanismekjede")
st.code(
    "hendelse → prisede forventninger → aktør/mandat → constraint/incentiv → ordreflow → likviditet → pris",
    language=None,
)

st.divider()
st.subheader("Aktørkart")
actors = [
    ("CTA / trend", "Pris, momentum, volatilitet", "Systematiske trendregler", "Trendforsterkning / mekanisk scale-in/out", "COT + modellert eksponering"),
    ("Macro / hedgefond", "Makro, rates, FX, relative value", "Avkastning / asymmetri", "Cross-asset reprising", "COT / 13F / fund-flow, ofte aggregert"),
    ("Optionsdealere", "Delta, gamma, vega, inventory", "Holde bok hedget", "Mekanisk hedging rundt pris/strikes", "Options OI/volum + inferert dealer-side"),
    ("Vol-control / risk parity", "Volatilitet, korrelasjon, risiko", "Målstyrt porteføljerisiko", "De-/releveraging", "Vol/korrelasjon + modellert pressure"),
    ("Pensjon / long-only", "Allokering, benchmark, liabilities", "Mandat / langsiktig allokering", "Rebalansering", "Holdings/fund-flow/rebalansering"),
    ("Passive / ETF", "Indeksvekter og investor-flow", "Tracking", "Creation/redemption og rebalance", "ETF holdings/flows"),
    ("Corporate / hedgers", "Råvarer, valuta, finansiering", "Redusere virksomhetsrisiko", "Hedge-flow uten retningssyn", "Rapporter + futures positioning"),
    ("Sentralbank / offentlig", "Reserver, valuta, likviditet", "Policy / reserveforvaltning", "FX/rente/gull/liquidity-flow", "Balanser, reserver, offisielle rapporter"),
    ("Retail", "Pris, nyheter, sentiment", "Spekulasjon / investering", "Kan forsterke konsentrert momentum", "Broker-/options-/sentiment-proxies"),
]
for name, observes, motive, footprint, data in actors:
    with st.expander(name):
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**Ser på**\n\n{observes}")
        c2.markdown(f"**Mandat / constraint**\n\n{motive}")
        c3.markdown(f"**Mulig avtrykk**\n\n{footprint}")
        c4.markdown(f"**Hva vi kan få data på**\n\n{data}")

st.divider()
st.subheader("Tre lag i samme marked")
tech, world, actor = st.columns(3)
tech.markdown("### Teknisk")
tech.write("Trend · volatilitet · momentum · korrelasjon · likviditet · termstruktur")
world.markdown("### Verden / nyheter")
world.write("Vekst · inflasjon · renter · energi · geopolitikk · selskaper · policy")
actor.markdown("### Aktører")
actor.write("Hvem kan være marginal kjøper/selger, og hvilke regler eller constraints kan produsere flow?")

st.subheader("Regime × aktør")
st.dataframe(
    pd.DataFrame(
        {
            "Aktør": ["CTA", "Dealers", "Macro", "Vol-control", "Long-only"],
            "Trend": ["høy", "indirekte", "høy", "indirekte", "lav/moderat"],
            "Volatilitet": ["høy", "svært høy", "høy", "svært høy", "moderat"],
            "Makronyhet": ["via pris", "via vol/hedging", "svært høy", "via risiko", "høy"],
            "Rebalansering": ["lav", "moderat", "moderat", "moderat", "svært høy"],
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.subheader("Snapshot-kontrakten")
st.markdown(
    """
    Et senere ekte snapshot skal være lite, men reviderbart: **hendelse + relevante målverdier + analyse + evidens + proveniens**.
    Vi lagrer ikke en massiv kopi av råfeedene. Revisjoner appendes i stedet for å overskrive historien.

    **Observed → Inferred → Later confirmed / weakened / refuted**
    """
)
st.caption(
    f"Prototype renderet {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
    "Demoen er statisk og skal ikke tolkes som en analyse av dagens marked."
)
st.warning(
    "Aktøridentitet er ofte latent. 'CTA solgte' er ikke et faktum uten direkte evidens. "
    "Siden skal eksplisitt merke forskjellen mellom måling, inferens og senere bekreftelse."
)
