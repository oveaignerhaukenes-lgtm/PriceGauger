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

with st.expander("❓ Hvordan lese analysen?", expanded=False):
    st.markdown(
        """
        **Observert** betyr at påstanden kommer direkte fra tilgjengelige data, for eksempel pris, rente eller rapportert posisjonering.  
        **Inferert** betyr at dataene passer med en mekanisme, men ikke identifiserer aktøren eller årsaken direkte.  
        **Bekreftet** betyr at senere data styrker en tidligere hypotese vesentlig.  
        **Svekket** betyr at senere data gjør hypotesen mindre sannsynlig.  
        **Avkreftet** betyr at senere evidens er uforenlig med den opprinnelige forklaringen.

        **Confidence** sier hvor sterkt evidensgrunnlaget er, ikke hvor dramatisk markedsbevegelsen var. En stor bevegelse kan fortsatt ha en forklaring med lav confidence.
        """
    )

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
with st.expander("❓ Hva betyr ordreflow og likviditet?", expanded=False):
    st.markdown(
        """
        **Ordreflow** er strømmen av faktiske kjøps- og salgsordre som møter markedets tilgjengelige likviditet. En nyhet flytter ikke prisen direkte: den endrer aktørenes incentiver eller constraints, som igjen skaper ordre.

        **Likviditet** er hvor mye kjøps- og salgsinteresse som finnes rundt gjeldende pris. Aggressive kjøpere konsumerer tilbud på ask; aggressive selgere konsumerer bud. Hvis ordrene er store relativt til tilgjengelig likviditet, må prisen ofte flytte seg mer for å finne motpart.

        **Absorption** oppstår når mye aggressiv ordreflow møter en stor passiv motpart og prisen derfor beveger seg mindre enn volumet skulle tilsi.
        """
    )

st.divider()
st.subheader("Aktørkart")
actors = [
    (
        "CTA / trend",
        "Commodity Trading Advisor. I denne sammenhengen særlig systematiske fond som følger regler basert på trend, momentum og volatilitet. De kan kjøpe fordi markedet allerede stiger eller selge fordi det faller, og dermed forsterke en eksisterende bevegelse. CTA-aktivitet er ofte inferert fra pris, volatilitet og senere posisjoneringsdata — ikke direkte identifisert ordre for ordre.",
        "Pris, momentum, volatilitet",
        "Systematiske trendregler",
        "Trendforsterkning / mekanisk scale-in/out",
        "COT + modellert eksponering",
    ),
    (
        "Macro / hedgefond",
        "Diskresjonære eller systematiske fond som handler makroøkonomiske sammenhenger på tvers av renter, valuta, aksjer og råvarer. De kan reagere raskt når ny informasjon endrer forventninger til vekst, inflasjon eller sentralbankpolitikk.",
        "Makro, rates, FX, relative value",
        "Avkastning / asymmetri",
        "Cross-asset reprising",
        "COT / 13F / fund-flow, ofte aggregert",
    ),
    (
        "Optionsdealere",
        "Market makers som står på motsatt side av kundenes opsjonshandler og ofte hedger delta- og gammaeksponeringen i underliggende marked. Hedgingen kan skape mekaniske kjøp eller salg uten at dealeren har et retningssyn.",
        "Delta, gamma, vega, inventory",
        "Holde bok hedget",
        "Mekanisk hedging rundt pris/strikes",
        "Options OI/volum + inferert dealer-side",
    ),
    (
        "Vol-control / risk parity",
        "Strategier som skalerer eksponering etter målt risiko. Når volatiliteten øker kan de bli tvunget til å redusere posisjoner; når volatiliteten faller kan de øke igjen. Flowen kan derfor være mekanisk og etterslepende.",
        "Volatilitet, korrelasjon, risiko",
        "Målstyrt porteføljerisiko",
        "De-/releveraging",
        "Vol/korrelasjon + modellert pressure",
    ),
    (
        "Pensjon / long-only",
        "Store langsiktige investorer med allokerings-, benchmark- og liability-krav. De handler ofte langsommere enn spekulative fond, men størrelsen gjør rebalanseringer viktige.",
        "Allokering, benchmark, liabilities",
        "Mandat / langsiktig allokering",
        "Rebalansering",
        "Holdings/fund-flow/rebalansering",
    ),
    (
        "Passive / ETF",
        "Kapital som følger indeks eller fondskonstruksjon fremfor et aktivt markedssyn. Investorinn- og utbetalinger, indeksendringer og rebalansering kan skape forutsigbare handelsbehov.",
        "Indeksvekter og investor-flow",
        "Tracking",
        "Creation/redemption og rebalance",
        "ETF holdings/flows",
    ),
    (
        "Corporate / hedgers",
        "Selskaper og kommersielle aktører som bruker markedet for å redusere virksomhetsrisiko, for eksempel valuta-, råvare- eller renterisiko. En stor handel trenger derfor ikke uttrykke et syn på retningen.",
        "Råvarer, valuta, finansiering",
        "Redusere virksomhetsrisiko",
        "Hedge-flow uten retningssyn",
        "Rapporter + futures positioning",
    ),
    (
        "Sentralbank / offentlig",
        "Sentralbanker, finansdepartementer og andre offentlige aktører som påvirker markeder gjennom policy, reserver, likviditet, valutaoperasjoner og reserveforvaltning. Motivet er ofte stabilitet eller policy, ikke maksimal tradingavkastning.",
        "Reserver, valuta, likviditet",
        "Policy / reserveforvaltning",
        "FX/rente/gull/liquidity-flow",
        "Balanser, reserver, offisielle rapporter",
    ),
    (
        "Retail",
        "Private investorer og tradere. Gruppen er heterogen, men kan bli viktig når aktivitet konsentreres i samme instrument, opsjonsstrike eller narrativ og dermed forsterker momentum eller dealer-hedging.",
        "Pris, nyheter, sentiment",
        "Spekulasjon / investering",
        "Kan forsterke konsentrert momentum",
        "Broker-/options-/sentiment-proxies",
    ),
]
for name, explanation, observes, motive, footprint, data in actors:
    with st.expander(f"❓ {name}"):
        st.write(explanation)
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

with st.expander("❓ Begreper som dukker opp i analysen", expanded=False):
    glossary = pd.DataFrame(
        [
            ["COT", "Commitments of Traders: periodisk posisjoneringsrapport for futuresmarkeder."],
            ["Open interest (OI)", "Antall utestående futures- eller opsjonskontrakter som fortsatt er åpne."],
            ["Delta", "Hvor mye en opsjonsverdi omtrent endres når underliggende pris flytter seg én enhet."],
            ["Gamma", "Hvor raskt opsjonens delta endrer seg når underliggende pris flytter seg."],
            ["Deleveraging", "Reduksjon av eksponering eller gearing, ofte fordi risiko/volatilitet har økt."],
            ["Rebalansering", "Handler som bringer en portefølje tilbake mot ønskede vekter eller risikomål."],
            ["Cross-asset", "Sammenheng eller reprising på tvers av aktivaklasser, f.eks. renter → USD → tech → gull."],
            ["Positioning", "Hvordan markedsaktører allerede er eksponert long, short eller relativt til en benchmark."],
        ],
        columns=["Begrep", "Kort forklaring"],
    )
    st.dataframe(glossary, use_container_width=True, hide_index=True)

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
