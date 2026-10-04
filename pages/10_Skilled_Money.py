from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from saxo_provider import SaxoError, configured_client
from skilled_money_workspace_v1 import (
    add_watch_v1,
    create_manual_event_v1,
    list_events_v1,
    list_revisions_v1,
    list_watches_v1,
    set_watch_active_v1,
)


st.title("Skilled Money")
st.caption("Retrospektiv læring: fra markedsbevegelse til aktører, constraints, ordreflow og senere bekreftelse.")
st.info(
    "Læringsflate, ikke trading-signal. AutoTrader og execution leser ikke denne siden. "
    "Vi lagrer hendelser og kompakte analyserevisjoner — ikke en kontinuerlig kopi av rå markedsfeeds."
)

with st.expander("❓ Hvordan lese analysen?", expanded=False):
    st.markdown(
        """
        **Observert** = direkte tilgjengelige data. **Inferert** = dataene passer med en mekanisme, men identifiserer ikke aktøren direkte.
        **Bekreftet / Svekket / Avkreftet** brukes når senere data endrer evidensbildet. **Confidence** gjelder evidensstyrke, ikke størrelsen på markedsbevegelsen.
        """
    )

st.subheader("Markeder som følges")
st.caption("Saxo er første provider-binding. Canonical market holdes generisk slik at andre datakilder kan kobles til samme marked senere.")
try:
    watches = list_watches_v1()
except Exception as exc:
    watches = ()
    st.error(f"Kunne ikke lese watchlist: {exc}")

if watches:
    for watch in watches:
        left, right = st.columns([5, 1])
        left.markdown(f"**{watch.display_name}** · `{watch.canonical_market}`  \n{watch.provider.upper()} · {watch.symbol or '—'} · UIC {watch.provider_instrument_id} · {watch.asset_type or '—'}")
        if right.button("Fjern", key=f"remove-watch-{watch.watch_id}"):
            set_watch_active_v1(watch.watch_id, False)
            st.rerun()
else:
    st.write("Ingen markeder er lagt til ennå.")

with st.expander("＋ Legg til marked fra Saxo", expanded=not bool(watches)):
    query = st.text_input("Søk i Saxo-instrumenter", placeholder="f.eks. US Tech, Gold, Brent, USDJPY")
    if st.button("Søk", key="skilled-money-saxo-search", disabled=len(query.strip()) < 2):
        client = configured_client()
        if client is None:
            st.warning("Saxo er ikke konfigurert i denne runtime-en.")
        else:
            try:
                st.session_state["skilled_money_saxo_results"] = client.search_instruments(query.strip())[:30]
            except SaxoError as exc:
                st.error(f"Saxo-søk feilet: {exc}")
    results = st.session_state.get("skilled_money_saxo_results", [])
    if results:
        labels = {f"{item.description or item.symbol or item.uic} · {item.symbol or '—'} · {item.asset_type} · UIC {item.uic}": item for item in results}
        selected_label = st.selectbox("Saxo-resultat", tuple(labels))
        selected = labels[selected_label]
        canonical_default = (selected.symbol or selected.description or query).strip().upper().replace(" ", "_")
        canonical = st.text_input("Canonical market", value=canonical_default, help="Generisk markedsidentitet; provider-spesifikk UIC lagres separat.")
        if st.button("＋ Følg dette markedet", key="skilled-money-add-watch"):
            add_watch_v1(canonical_market=canonical, display_name=selected.description or selected.symbol or canonical, provider="saxo", provider_instrument_id=selected.uic, asset_type=selected.asset_type, symbol=selected.symbol, metadata={"source": "saxo-search"})
            st.session_state.pop("skilled_money_saxo_results", None)
            st.rerun()

st.divider()
st.subheader("Undersøk en bestemt bevegelse")
st.caption("Bruk dette når du tenker «hva skjedde egentlig her?». Hendelsen lagres som T0 og kan få nye revisjoner når relevant data blir tilgjengelig senere.")
try:
    watches = list_watches_v1()
except Exception:
    watches = ()
if watches:
    watch_labels = {f"{watch.display_name} · {watch.canonical_market}": watch for watch in watches}
    with st.form("skilled-money-manual-event"):
        watch_label = st.selectbox("Marked", tuple(watch_labels))
        d1, t1, d2, t2 = st.columns(4)
        start_date = d1.date_input("Startdato")
        start_time = t1.time_input("Starttid", value=time(14, 30))
        end_date = d2.date_input("Sluttdato")
        end_time = t2.time_input("Sluttid", value=time(15, 30))
        move_summary = st.text_input("Hva gjorde markedet?", placeholder="f.eks. falt ca. 2 % på 45 minutter")
        question = st.text_area("Hva vil du forstå?", placeholder="Hvorfor kom fallet, hvem kan ha forsterket det, og hva vet vi først i ettertid?")
        submitted = st.form_submit_button("Opprett hendelse for retrospektiv analyse")
        if submitted:
            start = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
            end = datetime.combine(end_date, end_time, tzinfo=timezone.utc)
            if end < start:
                st.error("Sluttid kan ikke være før starttid.")
            elif not move_summary.strip():
                st.error("Beskriv kort selve markedsbevegelsen.")
            else:
                event_id = create_manual_event_v1(watch_id=watch_labels[watch_label].watch_id, event_started_at=start, event_ended_at=end, move_summary=move_summary, question=question)
                st.success(f"Hendelsen er lagret som T0 · {event_id[:8]}")
                st.rerun()
else:
    st.info("Legg til minst ett marked i watchlisten før du oppretter en hendelse.")

st.divider()
st.subheader("Hendelsesjournal")
try:
    stored_events = list_events_v1(limit=30)
except Exception as exc:
    stored_events = ()
    st.error(f"Kunne ikke lese hendelsesjournalen: {exc}")
if stored_events:
    for event in stored_events:
        with st.expander(f"{event.display_name} · {event.move_summary} · {event.event_started_at:%Y-%m-%d %H:%M} UTC"):
            st.markdown(f"**Canonical market:** `{event.canonical_market}` · **Status:** {event.status}")
            if event.question:
                st.markdown(f"**Spørsmål:** {event.question}")
            for revision in list_revisions_v1(event.event_id):
                st.markdown(f"**R{revision['revision']} · {revision['created_at']:%Y-%m-%d %H:%M} UTC**")
                st.write(revision["summary"])
                if revision["evidence"]:
                    st.dataframe(pd.DataFrame(revision["evidence"]), use_container_width=True, hide_index=True)
else:
    st.caption("Ingen lagrede hendelser ennå. Demoen under viser hvordan en moden analyse kan se ut.")

example = {"title": "Eksempel · kraftig fall i US Tech 100", "move": "−2,1 % på 47 min", "status": "RETROSPEKTIV · DEMO", "initial": "Renter steg samtidig som tech falt. Makro/reprising er direkte observerbart; systematisk deleveraging er foreløpig bare en hypotese.", "later": "Senere positioning-/flowdata kan styrke, svekke eller avkrefte hypotesen. Den opprinnelige vurderingen beholdes uendret."}
with st.expander("Vis demo av et analysert hendelseskort", expanded=not bool(stored_events)):
    with st.container(border=True):
        a, b, c = st.columns([2, 1, 1]); a.markdown(f"### {example['title']}"); b.metric("Bevegelse", example["move"]); c.metric("Status", example["status"])
        st.markdown("**T0 · hva kunne vi si da?**"); st.write(example["initial"]); st.markdown("**T+ · hva kan senere data endre?**"); st.write(example["later"])
    evidence = pd.DataFrame([["Pris", "Tech falt raskt", "Observert", "Høy", "T0"], ["Rates", "Renter steg samtidig", "Observert", "Høy", "T0"], ["Volatilitet", "Volatilitet ekspanderte", "Observert", "Høy", "T0"], ["Macro funds", "Reprising kan ha bidratt", "Inferert", "Middels", "T0"], ["CTA / systematic", "Deleveraging kan ha forsterket bevegelsen", "Inferert", "Lav", "T0"], ["Leveraged funds", "Kan senere kontrolleres mot positioning", "Avventer data", "—", "T+ dager"]], columns=["Lag", "Påstand", "Type", "Confidence", "Tilgjengelig"])
    st.dataframe(evidence, use_container_width=True, hide_index=True)
    st.dataframe(pd.DataFrame({"Fase": ["T0", "T+1d", "T+1 uke", "T+uker"], "Typiske nye data": ["pris · volum · rates · FX · vol · nyheter", "options/OI · ETF/flow · dagsdata", "CFTC/COT · bredere positioning", "holdings · reserve-/fondrapporter · revisjoner"], "Handling": ["opprett første forklaring", "legg til revisjon", "bekreft/svekk aktørhypoteser", "lukk eller behold usikker forklaring"]}), use_container_width=True, hide_index=True)

st.markdown("#### Mekanismekjede")
st.code("hendelse → prisede forventninger → aktør/mandat → constraint/incentiv → ordreflow → likviditet → pris", language=None)
with st.expander("❓ Hva betyr ordreflow og likviditet?", expanded=False):
    st.markdown("**Ordreflow** er strømmen av faktiske kjøps- og salgsordre som møter markedets tilgjengelige likviditet. En nyhet endrer aktørenes incentiver eller constraints, som igjen skaper ordre. **Likviditet** er hvor mye kjøps- og salgsinteresse som finnes rundt gjeldende pris. **Absorption** oppstår når mye aggressiv ordreflow møter en stor passiv motpart.")

st.divider(); st.subheader("Aktørkart")
actors = [("CTA / trend", "Systematiske fond som følger regler basert på trend, momentum og volatilitet.", "Pris, momentum, volatilitet", "Systematiske trendregler", "Trendforsterkning / mekanisk scale-in/out", "COT + modellert eksponering"), ("Macro / hedgefond", "Fond som handler makroøkonomiske sammenhenger på tvers av markeder.", "Makro, rates, FX", "Avkastning / asymmetri", "Cross-asset reprising", "COT / 13F / fund-flow"), ("Optionsdealere", "Market makers som ofte hedger delta- og gammaeksponering.", "Delta, gamma, vega", "Holde bok hedget", "Mekanisk hedging", "Options OI/volum"), ("Vol-control / risk parity", "Strategier som skalerer eksponering etter målt risiko.", "Volatilitet, korrelasjon", "Målstyrt risiko", "De-/releveraging", "Vol/korrelasjon + modell"), ("Pensjon / long-only", "Store langsiktige investorer med allokeringskrav.", "Allokering, benchmark", "Langsiktig mandat", "Rebalansering", "Holdings/fund-flow"), ("Passive / ETF", "Kapital som følger indeks eller fondskonstruksjon.", "Indeksvekter og flow", "Tracking", "Creation/redemption", "ETF holdings/flows"), ("Corporate / hedgers", "Kommersielle aktører som reduserer virksomhetsrisiko.", "Råvarer, valuta", "Hedging", "Hedge-flow", "Rapporter + futures"), ("Sentralbank / offentlig", "Offentlige aktører med policy- og reserveformål.", "Reserver, valuta", "Policy", "FX/rente/gull-flow", "Offisielle rapporter"), ("Retail", "Private investorer og tradere.", "Pris, nyheter, sentiment", "Spekulasjon", "Konsentrert momentum", "Sentiment/options-proxies")]
for name, explanation, observes, motive, footprint, data in actors:
    with st.expander(f"❓ {name}"):
        st.write(explanation); c1, c2, c3, c4 = st.columns(4); c1.markdown(f"**Ser på**\n\n{observes}"); c2.markdown(f"**Mandat / constraint**\n\n{motive}"); c3.markdown(f"**Mulig avtrykk**\n\n{footprint}"); c4.markdown(f"**Data**\n\n{data}")

st.divider(); st.subheader("Tre lag i samme marked")
tech, world, actor = st.columns(3); tech.markdown("### Teknisk"); tech.write("Trend · volatilitet · momentum · korrelasjon · likviditet"); world.markdown("### Verden / nyheter"); world.write("Vekst · inflasjon · renter · energi · geopolitikk · policy"); actor.markdown("### Aktører"); actor.write("Hvem kan være marginal kjøper/selger, og hvilke regler eller constraints kan produsere flow?")
with st.expander("❓ Begreper som dukker opp i analysen", expanded=False):
    st.dataframe(pd.DataFrame([["COT", "Commitments of Traders: periodisk futures-posisjonering."], ["Open interest (OI)", "Antall utestående futures- eller opsjonskontrakter."], ["Delta", "Opsjonens omtrentlige prisfølsomhet mot underliggende."], ["Gamma", "Hvor raskt delta endrer seg."], ["Deleveraging", "Reduksjon av eksponering/gearing."], ["Rebalansering", "Handler tilbake mot ønskede vekter eller risikomål."], ["Cross-asset", "Reprising på tvers av aktivaklasser."], ["Positioning", "Hvordan aktører allerede er eksponert long/short."]], columns=["Begrep", "Kort forklaring"]), use_container_width=True, hide_index=True)

st.subheader("Snapshot-kontrakten")
st.markdown("Et ekte snapshot er lite, men reviderbart: **hendelse + relevante målverdier + analyse + evidens + proveniens**. Vi lagrer ikke en massiv kopi av råfeedene. Revisjoner appendes i stedet for å overskrive historien.\n\n**Observed → Inferred → Later confirmed / weakened / refuted**")
st.caption(f"Renderet {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Automatisk event-detektor kommer først etter at watchlist + manuelle hendelser er prøvd i praksis.")
st.warning("Aktøridentitet er ofte latent. 'CTA solgte' er ikke et faktum uten direkte evidens.")
