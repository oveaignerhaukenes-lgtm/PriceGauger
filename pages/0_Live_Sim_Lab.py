"""Read-only observability panel for forward Live-Sim Lab research."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from database import connect
from live_sim_lab_store_v1 import lab_equity_points, lab_snapshot, MAX_ACTIVE_LAB_VARIANTS

st.title("Live-Sim Lab")
st.caption("Fremoverrettede papirforsøk · ingen Saxo-ordrer · inkrementelle tekniske regimer")

try:
    experiments, memory, feeds = lab_snapshot()
except Exception as exc:
    st.error("Lab-data kunne ikke lastes. Undersøk databasetilkobling og schema.")
    st.exception(exc)
    st.stop()

active = [x for x in experiments if x["status"] == "ACTIVE"]
observed = [x for x in experiments if x["last_bar"]]
cols = st.columns(4)
cols[0].metric("Aktive varianter", f"{len(active)} / {MAX_ACTIVE_LAB_VARIANTS}")
cols[1].metric("Med observasjoner", len(observed))
cols[2].metric("Markeder", len(feeds))
cols[3].metric("Handler (SIM)", sum(x["trades"] for x in experiments))

if not feeds:
    st.warning(
        "Ingen lab-worker har initialisert markedsstrømmen ennå. "
        "Den må kjøres som separat Railway-service mot delt PostgreSQL."
    )
    st.stop()

for feed in feeds:
    st.caption(
        f"Datastrøm: {feed['market_name']} / instrument {feed['instrument_id']} "
        f"· siste ferdige 1m-bar {feed['last_bar_time']} · oppdatert {feed['updated_at']}"
    )

st.info(
    "V1 benytter egne MACD-researchvarianter, ikke identiske produksjonsstrategier. "
    "Resultatene viser normalisert virtuell kapital, med en foreløpig kostnadsmodell "
    "(5 basispunkter per eksponeringsendring), ikke Saxo-resultat."
)

if not experiments:
    st.info("Datastrøm registrert. 72 varianter opprettes ved første bootstrap.")
    st.stop()

families = sorted({x["family"] for x in experiments})
modifiers = sorted({x["modifier"] for x in experiments})
f1, f2, f3 = st.columns(3)
family_filter = f1.multiselect("Strategitype", families, default=families)
modifier_filter = f2.multiselect("Modifikator", modifiers, default=modifiers)
market_filter = f3.multiselect(
    "Marked", sorted({x["market_name"] for x in experiments}),
    default=sorted({x["market_name"] for x in experiments}),
)
filtered = [x for x in experiments if x["family"] in family_filter
            and x["modifier"] in modifier_filter and x["market_name"] in market_filter]
filtered.sort(key=lambda x:x["return_pct"], reverse=True)

st.subheader("Sammenligning av varianter")
visible = pd.DataFrame([{
    "ID": row["experiment_id"], "Marked": row["market_name"],
    "Strategi": row["family"], "S": f"{row['signal_tf']}m",
    "R": f"{row['regime_tf']}m", "Modifikator": row["modifier"],
    "Eksponering": row["max_exposure"],
    "Avkastning %": round(row["return_pct"], 3),
    "Maks fall %": round(row["max_drawdown_pct"], 3),
    "Sim-handler": row["trades"],
    "1m-barer":row.get("observed_bars",0),
    "Tid over 0 %":round(row.get("above_start_pct",0),1),
    "Positive 1m-barer %":round(row.get("positive_bar_pct",0),1),
    "Siste datapunkt": row["last_bar"] or "Ingen",
} for row in filtered])
st.dataframe(visible, hide_index=True, use_container_width=True, height=380)

if filtered:
    labels = {
        f"{x['family']} S{x['signal_tf']}/R{x['regime_tf']} "
        f"{x['modifier']} x{x['max_exposure']} · {x['experiment_id'][:6]}":x["experiment_id"]
        for x in filtered
    }
    selected = st.multiselect(
        "Velg inntil seks kurver", options=list(labels),
        default=list(labels)[:3], max_selections=6,
    )
    if selected:
        data = lab_equity_points([labels[label] for label in selected])
        if data:
            label_by_id = {value:key for key,value in labels.items()}
            timeseries = pd.DataFrame([{
                "Tid": pd.to_datetime(point["bar_time"],utc=True),
                "Variant": label_by_id.get(point["experiment_id"],point["experiment_id"]),
                "Avkastning %": (float(point["equity"])/10000.0-1.0)*100.0,
            } for point in data])
            plot = timeseries.pivot_table(index="Tid",columns="Variant",
                                          values="Avkastning %",aggfunc="last").sort_index()
            st.line_chart(plot, use_container_width=True)
        else:
            st.caption("Kurver vises først når nye markedsbarer har blitt behandlet.")

st.subheader("Regimekartlegging")
st.caption(
    "Utfallet for hver 1m-bar tilordnes regimet som var kjent FØR baren startet. "
    "Summerte NAV-enheter er ikke en separat rebased avkastningsprosent."
)
if memory:
    by_id = {x["experiment_id"]: x for x in experiments}
    regime_df = pd.DataFrame([{
        "Strategi": by_id.get(x["experiment_id"],{}).get("family","—"),
        "ID": x["experiment_id"][:8], "Regime": x["regime"],
        "Observerte barer": int(x["observed_bars"]),
        "Sum bidrag (NAV-enheter)": round(float(x["sum_delta_nav"]),2),
    } for x in memory if x["experiment_id"] in {p["experiment_id"] for p in filtered}])
    st.dataframe(regime_df,hide_index=True,use_container_width=True,height=260)
else:
    st.caption("Regimeminne bygges når første fremtidige 1m-bar observeres.")

st.subheader("Adaptiv strategiselektor (SHADOW)")
st.caption(
    "Tre uavhengige papirporteføljer: nylig ytelse, regimeminne og hybrid. "
    "Valg skjer etter ferdig bar og trer i kraft ved neste baråpning, med "
    "transaksjonskostnad og bytteslitasje. Ingen LIVE-tilgang eller Saxo-ordrer."
)
try:
    from live_sim_lab_evolution_v1 import evolution_snapshot, selector_equity_points
    selectors, trials, switching = evolution_snapshot()
except Exception as exc:
    st.warning("Evolusjonspanelet er foreløpig utilgjengelig.")
    st.caption(type(exc).__name__)
    selectors, trials, switching = [], [], []
if selectors:
    info = pd.DataFrame([{
        "Velger": row["selector_kind"],
        "Valgt strategi": str(row.get("selected_id") or "Ikke valgt")[:10],
        "Venter på": str(row.get("pending_id") or "Ingen")[:10],
        "Avkastning %": round((float(row.get("equity",10000.0))/10000-1)*100,3),
        "Maks fall %": round(float(row.get("max_drawdown",0))*100,3),
        "Bytter": int(row.get("switches",0)),
        "Kostede handler": int(row.get("trades",0)),
        "Siste bar": row.get("last_bar") or "Ingen",
    } for row in selectors])
    st.dataframe(info,hide_index=True,use_container_width=True)
    shadow_points = selector_equity_points()
    if shadow_points:
        frame=pd.DataFrame([{
            "Tid":pd.to_datetime(x["bar_time"],utc=True),
            "Selector":x["selector_kind"],
            "Papiravkastning %":(float(x["equity"])/10000-1)*100
        } for x in shadow_points])
        st.line_chart(frame.pivot_table(
            index="Tid",columns="Selector",values="Papiravkastning %",
            aggfunc="last").sort_index(),use_container_width=True)
    with st.expander("Siste selektorbeslutninger"):
        if switching:
            st.dataframe(pd.DataFrame([{
                "Tid":x["decision_bar"],"Velger":x["selector_kind"],
                "Fra":str(x.get("prior_id") or "Ingen")[:10],
                "Til":str(x.get("proposed_id") or "Ingen")[:10],
                "Årsak":x["reason"],
            } for x in switching]),hide_index=True,use_container_width=True)
        else:
            st.caption("Ingen strategibytter er foreslått ennå.")
else:
    st.caption("Selectorene begynner å evaluere etter tilstrekkelige fremoverrettede data.")

st.subheader("Evolusjon og perturbasjoner")
if trials:
    counts = {name:sum(t["status"]==name for t in trials)
              for name in ("QUEUED","RUNNING","RETIRED")}
    col1,col2,col3=st.columns(3)
    col1.metric("Aktive / undersøkes",counts["RUNNING"])
    col2.metric("På forskningskø",counts["QUEUED"])
    col3.metric("Pensjonert",counts["RETIRED"])
    st.caption(
        "Varianter får uforanderlig forsøks-ID. Svake varianter kan pensjoneres "
        "først etter omfattende data fra flere regimer og gjentatte kontroller. "
        "Pensjonerte forsøk slettes aldri og kjøres ikke automatisk om igjen."
    )
    stage=st.selectbox("Vis forsøksstatus",("QUEUED","RUNNING","RETIRED"))
    records=[x for x in trials if x["status"]==stage]
    st.dataframe(pd.DataFrame([{
        "ID":t["experiment_id"][:10],
        "Forelder":str(t.get("parent_id") or "Opprinnelig")[:10],
        "Familie":t["config"]["family"],
        "Signal":f'{t["config"]["signal_tf"]}m',
        "Regime":f'{t["config"]["regime_tf"]}m',
        "Modifikator":t["config"]["modifier"],
        "Eksponering":t["config"]["max_exposure"],
        "Start":t.get("started_at") or "Ikke testet",
        "Avsluttet":t.get("ended_at") or "—",
        "Avkastning %":round((t.get("outcome") or {}).get("return_pct",0),3)
            if t.get("outcome") else None,
    } for t in records]),hide_index=True,use_container_width=True,height=310)
    with st.expander("Fullstendige resultatdata fra pensjonerte forsøk"):
        if counts["RETIRED"]:
            st.json([{"ID":t["experiment_id"],**(t.get("outcome") or {})}
                     for t in trials if t["status"]=="RETIRED"][:30])
        else:
            st.caption("Ingen pensjoneringer. Kravene til evidens er bevisst strenge.")
else:
    st.caption("Perturbasjonskø bygges når worker har initialisert fremoverrettede varianter.")

st.subheader("Kontekstlab: makro × geopolitikk")
st.caption(
    "Fem på forhånd utvalgte kandidater måles parallelt som original, "
    "makrofilter, geopolitisk AI-kontekstfilter og begge samlet. "
    "Alle fire starter med samme papir-NAV, fylles først neste bar "
    "og belastes samme omsetningskostnad. Ingen LIVE-tilknytning."
)
try:
    from live_sim_lab_context_ablation_v1 import context_ablation_snapshot
    cohort, contextual, macro_health, paper_points = context_ablation_snapshot()
except Exception as exc:
    st.warning("Kontekstforsøket er foreløpig utilgjengelig.")
    st.caption(type(exc).__name__)
    cohort, contextual, macro_health, paper_points = [],[],None,[]
if macro_health:
    st.caption(f"Makrokalender: {macro_health['status']} · sist kontrollert "
               f"{macro_health['checked_at']}")
if not cohort:
    st.info("Kontekstforsøket starter når fem varianter har minst "
            "120 prospektive 1m-barer, nok handelshistorikk og sammenlignbar evidens.")
else:
    st.caption("Fast kohort: "+", ".join(x["experiment_id"][:8] for x in cohort))
    baselines={x["experiment_id"]:x for x in contextual if x["arm"]=="BASE"}
    report=[]
    for x in contextual:
        base=baselines.get(x["experiment_id"])
        nav=float(x.get("equity",10000.0))
        parent_nav=float(base.get("equity",10000.0)) if base else 10000.0
        bars=max(1,int(x.get("bars",0)))
        report.append({
            "Kandidat":x["experiment_id"][:10],"Arm":x["arm"],
            "Avkastning %":round((nav/10000-1)*100,3),
            "Vs. kontroll pp":round((nav-parent_nav)/100,3),
            "Maks fall %":round(float(x.get("max_drawdown",0))*100,3),
            "Handler":x.get("trades",0),"1m-barer":x.get("bars",0),
            "Makrodata %":round(100*x.get("macro_known",0)/bars,1),
            "Geopolitisk data %":round(100*x.get("geo_known",0)/bars,1),
            "Makrohendelser":x.get("macro_triggered",0),
            "Geopolitiske varsler":x.get("geo_triggered",0),
        })
    st.dataframe(pd.DataFrame(report),hide_index=True,use_container_width=True,height=380)
    if paper_points:
        chart=pd.DataFrame([{
            "Tid":pd.to_datetime(x["bar_time"],utc=True),
            "Forsøk":x["experiment_id"][:6]+" "+x["arm"],
            "Avkastning %":(float(x["equity"])/10000.0-1)*100
        } for x in paper_points])
        st.line_chart(chart.pivot_table(
            index="Tid",columns="Forsøk",values="Avkastning %",
            aggfunc="last").sort_index(),use_container_width=True)
    st.caption(
        "Manglende eller foreldet kilde gir ingen kontekstendring. "
        "Et risikofilter er ikke en retningsprediksjon. "
        "Geopolitiske mål gjenbruker eksisterende AI-genererte Context v2-"
        "snapshots med dokumentert opphav og tilgjengelighetstid. "
        "Datadekning og aktivitet må vurderes før rangering."
    )

st.subheader("Whipsaw Lab: Pause / Reduce / Flat")
st.caption(
    "Tester den eksisterende WHIPSAW-detektoren på fem fastlåste, "
    "umodifiserte LAB-strategier. Fire parallelle PAPER-spor: original, "
    "pause av nye innganger, halv eksponering og flat med karantene. "
    "Alle bruker samme lukkede 1m-signaler, neste baråpning og 5 bp kostnad."
)
try:
    from live_sim_lab_whipsaw_ablation_v1 import whipsaw_snapshot
    whip_parents, whip_tracks, whip_points = whipsaw_snapshot()
except Exception as exc:
    st.warning("Whipsaw-eksperimentet er ennå ikke tilgjengelig.")
    st.caption(type(exc).__name__)
    whip_parents, whip_tracks, whip_points = [], [], []
if not whip_parents:
    st.info("Samler kvalifikasjonsdata for fem strategier med minst 120 "
            "fremoverrettede barer og dokumenterte papirhandler. "
            "Tidligere markedssvingninger spilles ikke inn med etterpåklokskap.")
else:
    whip_controls={r["experiment_id"]:r for r in whip_tracks if r["arm"]=="BASE"}
    overview=[]
    for item in whip_tracks:
        control=whip_controls.get(item["experiment_id"])
        gain=100*(float(item.get("equity",10000.0))/10000-1)
        delta=(float(item.get("equity",10000.0))-
               float(control.get("equity",10000.0)))/100 if control else 0
        overview.append({
            "Strategi":item["experiment_id"][:10],
            "Policy":item["arm"],
            "P/L %":round(gain,3),
            "Mot BASE pp":round(delta,3),
            "Maks drawdown %":round(100*float(item.get("max_drawdown",0)),3),
            "Kostnader kr":round(float(item.get("transaction_cost_nok",0)),3),
            "Handler":item.get("trades",0),
            "Observerte barer":item.get("bars",0),
            "Whipsaw-barer":item.get("raw_whipsaw_bars",0),
            "Aktive risikobarer":item.get("effective_whipsaw_bars",0),
            "Blokkerte økninger":item.get("blocked_increases",0),
            "Reduksjoner":item.get("forced_reductions",0),
            "Tvungne flat":item.get("forced_flats",0),
        })
    st.dataframe(pd.DataFrame(overview),hide_index=True,
                 use_container_width=True,height=365)
    if whip_points:
        chart=pd.DataFrame([{
            "Tid":pd.to_datetime(x["bar_time"],utc=True),
            "Variant":x["experiment_id"][:5]+" "+x["arm"],
            "Papir-P/L %":100*(float(x["equity"])/10000-1),
        } for x in whip_points])
        st.line_chart(chart.pivot_table(index="Tid",columns="Variant",
            values="Papir-P/L %",aggfunc="last").sort_index(),
            use_container_width=True)
    st.caption(
        "Samme detektor som eksisterende WHIPSAW: ≥7 fortegnsskifter "
        "på 12 lukkede 1m-returer og Efficiency Ratio <0,35. "
        "Umiddelbar aktivering, tre rolige barer før frigjøring. "
        "REDUCE har maks 50 % nominell eksponering i whipsaw; "
        "FLAT krever også tre rolige barer før ny oppbygging. "
        "LAB-proxy, ikke Saxo-realiserte resultater. Ingen LIVE-effekt."
    )

st.subheader("Hyper-Vigilant Stochastic · sekundsignaler")
st.caption(
    "Eget PAPER-forsøk på faktiske, omsettelige Saxo bid/ask-kurser (maks 1 per "
    "sekund). Stochastic styrer retningen, MACD brukes bare når Stochastic "
    "flater ut, og pris kan overstyre ved tilstrekkelig motbevegelse. "
    "Alle handler simuleres først på neste observerte kurs."
)
with st.expander("Hvordan fungerer Hyper-Vigilant – og whipsaw-beskyttelsen?"):
    st.markdown(
        "**STOCH_ONLY:** følger retningen i Stochastic K (60 sekunder) "
        "med D-utjevning, uten ytterligere filtre.\n\n"
        "**STOCH_MACD:** lar MACD-histogrammet bestemme retning når "
        "Stochastic beveger seg sidelengs.\n\n"
        "**STOCH_PRICE:** legger til prisbasert nødutgang. En motbevegelse "
        "over maks(0,06 %, adaptiv 15s-støygrense) eller 0,12 % fra inngang "
        "sender posisjonen mot FLAT.\n\n"
        "**WHIP_PAUSE:** hindrer nye innganger under identifisert whipsaw. "
        "**WHIP_REDUCE:** begrenser posisjonen til halv størrelse. "
        "**WHIP_FLAT:** går flat og venter på tre rolige 5s-perioder "
        "før ny oppbygging.\n\n"
        "Fast whipsaw: minst 7 fortegnsskifter i 12 ferdige 5s-avkastninger "
        "og Efficiency Ratio under 0,35; hysterese før frigivelse. "
        "Minimum 8 sekunder mellom posisjonsøkninger, men tapstruende "
        "utganger kan skje raskere. "
        "Pris-/whipsaw-filter sammenlignes alltid med samme STOCH_PRICE-kontroll. "
        "Dette er forskning, ikke LIVE."
    )
try:
    from live_sim_hyper_vigilant_v1 import hyper_snapshot
    from live_sim_hyper_quotes_v1 import hyper_quote_status
    hv_feeds,hv_tracks,hv_points=hyper_snapshot()
    hv_quotes=hyper_quote_status()
except Exception as exc:
    st.warning("Hyper-Vigilant-data kan ikke leses ennå.")
    st.caption(type(exc).__name__)
    hv_feeds,hv_tracks,hv_points,hv_quotes=[],[],[],[]
if not hv_quotes:
    st.info(
        "Venter på første nye, udela­yede og omsettelige Tech100-kurs fra "
        "Saxo-strømmen. Ingen historiske sekunder konstrueres."
    )
else:
    for q in hv_quotes:
        st.caption(
            f"Prisstrøm {q['market_name']} / Saxo UIC {q['provider_uic']}: "
            f"{q['captured_quotes']} ekte 1s-punkter, siste {q['last_quote']}"
        )
if not hv_tracks:
    st.info(
        "Papirsporene initialiseres først etter at kursstrømmen har startet. "
        "Tidligere kurser kan varme indikatorene, men får aldri kunstig P/L."
    )
else:
    groups={}
    for row in hv_tracks:
        groups.setdefault(row["provider_uic"],{})[row["arm"]]=row
    results=[]
    for market,arms in groups.items():
        baseline=arms.get("STOCH_PRICE")
        for row in arms.values():
            delta=(float(row["equity"])-float(baseline["equity"]))/100 if baseline else 0
            results.append({
                "Saxo UIC":market,
                "Variant":row["arm"],
                "Netto P/L %":round((float(row["equity"])/10000-1)*100,3),
                "Mot pris-kontroll (pp)":round(delta,3),
                "Maks drawdown %":round(100*float(row["max_drawdown"]),3),
                "Papirhandler":row["trades"],
                "Bid/ask-kostnad kr":round(row["spread_cost_nok"],2),
                "Andre kostnader kr":round(row["fees_nok"],2),
                "Kurspunkter":row["ticks"],
                "Prisoverstyringer":row["price_guards"],
                "Whipsaw-punkter":row["whipsaw_bars"],
                "Whipsaw-blokkeringer":row["whipsaw_blocks"],
                "Whipsaw-reduksjoner":row["whipsaw_reductions"],
                "Whipsaw-flat":row["whipsaw_flats"],
                "MACD-reserver":row["macd_fallbacks"],
                "Databrudd":row["stale_ticks"],
                "Siste beslutning":row["last_reason"],
            })
    st.dataframe(pd.DataFrame(results),hide_index=True,use_container_width=True,
                 height=310)
    if hv_points:
        pointframe=pd.DataFrame([{
            "Tid":pd.to_datetime(x["quote_at"],utc=True),
            "Arm":x["arm"],
            "Netto P/L %":100*(float(x["equity"])/10000-1),
        } for x in hv_points])
        for market in sorted({x["provider_uic"] for x in hv_points}):
            eligible=pointframe.copy() if len(groups)==1 else pd.DataFrame([
                {"Tid":pd.to_datetime(x["quote_at"],utc=True),
                 "Arm":x["arm"],"Netto P/L %":100*(float(x["equity"])/10000-1)}
                for x in hv_points if x["provider_uic"]==market
            ])
            if not eligible.empty:
                st.line_chart(eligible.pivot_table(
                    index="Tid",columns="Arm",values="Netto P/L %",
                    aggfunc="last").sort_index(),use_container_width=True)
    st.caption(
        "Utvalget er prospektivt, med en papirportefølje på 10 000 "
        "normaliserte kroner per variant. Signal ved observert kurs t kan "
        "fylles tidligst på neste faktiske quote; ingen interpolerte ticks. "
        "Estimert bid/ask-halvspread + 2 bp per absolutt eksponeringsendring. "
        "Datagap over 5s stanser nye sim-ordre til ekte data igjen foreligger. "
        "Dette er ikke Saxo-posisjoner, og ingen modell har LIVE-fullmakt."
    )

ai_left, ai_right = st.columns([1.9,1],gap="large")
with ai_left:
    st.subheader("AI Trader v1 · teknisk PAPER")
    st.caption(
        "Selvstendig AI-beslutningstaker som kan foreslå LONG, SHORT, FLAT "
        "eller å redusere eksisterende posisjoner. Kun teknisk analyse: "
        "pris, Stochastic, MACD, whipsaw, volatilitet og papirresultater. "
        "Ingen nyheter, geopolitikk eller makroøkonomi."
    )
    with st.expander("Når vurderer AI – og hva får den lov til?"):
        st.markdown(
            "En ny vurdering kan skje hvert **180. sekund**, eller når en "
            "åpen posisjon har hatt minst **60 sekunder** sammenhengende "
            "ugunstig bevegelse større enn normal spread/støy. "
            "Mellom vurderingene overvåkes hver mottatte kurs for "
            "fiktivt papirresultat.\n\n"
            "Minst **90 sekunder mellom AI-forespørsler**, høyst 80 per "
            "dag og marked. Modellen foreslår ønsket posisjon i "
            "trinnene -1 / -0,5 / 0 / +0,5 / +1. "
            "Risikogaten begrenser nye økninger til 0,5 om gangen, "
            "krever flat før reversering og blokkerer økt eksponering "
            "ved whipsaw. Lav konfidens betyr ingen endring.\n\n"
            "Hver forespørsel har datatidsstempel og lagret begrunnelse. "
            "Et sent svar forkastes. Papirordren fylles **tidligst på neste "
            "faktiske observerte bid/ask-kurs** med spread- og "
            "transaksjonskostnad. Ingen Saxo-ordre eller LIVE-fullmakt."
        )
    try:
        from live_sim_ai_technical_trader_v1 import ai_technical_snapshot
        ai_accounts,ai_decisions,ai_points=ai_technical_snapshot()
    except Exception as exc:
        st.warning("AI Trader PAPER kan foreløpig ikke laste sine data.")
        st.caption(type(exc).__name__)
        ai_accounts,ai_decisions,ai_points=[],[],[]
    if not ai_accounts:
        st.info(
            "Venter på første ferske Tech100-kurs fra opptakeren. "
            "AI forsøker ikke å handle på tidligere observerte data."
        )
    else:
        ai_rows=[]
        hyper_reference={x["provider_uic"]:x for x in hv_tracks
                         if x.get("arm")=="STOCH_PRICE"}
        for account in ai_accounts:
            baseline=hyper_reference.get(account["provider_uic"])
            initial=account.get("paired_baseline_equity")
            paired_delta=None
            if baseline and initial and float(initial)>0:
                paired_return=(float(baseline["equity"])/float(initial)-1)*100
                ai_return=(float(account["equity"])/10000-1)*100
                paired_delta=round(ai_return-paired_return,3)
            ai_rows.append({
                "Saxo UIC":account["provider_uic"],
                "PAPER P/L %":round((float(account["equity"])/10000-1)*100,3),
                "Mot Stoch+pris (pp)":paired_delta,
                "Maks drawdown %":round(100*float(account["max_drawdown"]),3),
                "Eksponering":account["exposure"],
                "Papirhandler":account["trades"],
                "Samlede kostnader kr":round(
                    float(account["fees_nok"])+float(account["spread_cost_nok"]),2),
                "AI-vurderinger":account["ai_calls"],
                "Akseptert":account["accepted_decisions"],
                "Tapsvurderinger":account["loss_triggers"],
                "Forkastede AI-svar":account["rejected_requests"],
                "Databrudd":account["data_gaps"],
                "Siste status":account["last_model_status"],
            })
        st.dataframe(pd.DataFrame(ai_rows),hide_index=True,
                     use_container_width=True,height=200)
        if ai_points:
            ai_plot=pd.DataFrame([{
                "Tid":pd.to_datetime(x["quote_at"],utc=True),
                "PAPER P/L %":(float(x["equity"])/10000-1)*100,
            } for x in ai_points])
            st.line_chart(ai_plot.set_index("Tid")[["PAPER P/L %"]].sort_index(),
                          use_container_width=True)
        st.caption(
            "AI Trader er et uavhengig, kostnadsbelastet PAPER-eksperiment. "
            "Kontrollsporet STOCH_PRICE vises kun som relativ avkastning fra "
            "AI-start hvis samme datasett er tilgjengelig. "
            "Ingen AI-forslag kan endre V3 LIVE-kontoer eller Saxo-ordrer."
        )

with ai_right:
    st.markdown("#### AI-vurderinger · løpende")

    @st.fragment(run_every="10s")
    def _render_ai_decision_ticker():
        # Renders independently: recent AI reasons become visible without
        # repeatedly recomputing the heavy Live-Sim comparison tables.
        from live_sim_ai_technical_status_v1 import (
            load_ai_technical_status,load_ai_decision_feed,
        )
        try:
            ai_status=load_ai_technical_status()
            entries=load_ai_decision_feed(limit=30)
        except Exception as exc:
            st.warning("Kunne ikke lese AI-status og beslutninger.")
            st.caption(type(exc).__name__)
            return
        st.metric("AI Trader-status",ai_status["label"])
        st.caption(ai_status["detail"])
        if ai_status["last_tick"]:
            st.caption(
                "Sist observert worker: "
                +pd.to_datetime(ai_status["last_tick"],utc=True).tz_convert(
                    "Europe/Oslo").strftime("%H:%M:%S")
            )
        with st.container(height=520,border=True):
            if not entries:
                st.info(
                    "Ingen AI-vurderinger ennå. Meldinger kommer her "
                    "så snart tekniske data er tilstrekkelige."
                )
            for row in entries:
                stamp=pd.to_datetime(
                    row["requested_at"],utc=True,errors="coerce")
                clock=(stamp.tz_convert("Europe/Oslo").strftime("%H:%M:%S")
                       if not pd.isna(stamp) else str(row["requested_at"]))
                target=row.get("target")
                action=("LONG" if target is not None and target>0
                        else "SHORT" if target is not None and target<0
                        else "FLAT" if target is not None else "VENTER")
                st.markdown(
                    f"**{clock} · {action} · {row['event_kind']}**"
                )
                st.caption(
                    f"Status {row['model_status']} · "
                    f"mål {target if target is not None else '—'} · "
                    f"konfidens {row.get('confidence') if row.get('confidence') is not None else '—'}"
                )
                if row.get("reason"):
                    st.write(row["reason"])
                if row.get("gate_reason"):
                    st.caption(f"Risikogate: {row['gate_reason']}")
                st.divider()
        st.caption(
            "Nyeste øverst · automatisk oppdatering hvert 10. sekund · "
            "kun papirhandel."
        )

    _render_ai_decision_ticker()

st.subheader("Kveldsrapport og forskningskø")
with connect() as db:
    item = db.execute(
        "SELECT report_date,data_json FROM lsim_daily_reports ORDER BY report_date DESC LIMIT 1"
    ).fetchone()
if item is None:
    st.caption("Første faktabaserte kveldsrapport registreres kl. 20:00 Europe/Oslo.")
else:
    report = json.loads(item["data_json"])
    st.write(f"**Siste rapport: {item['report_date']}** · {report.get('observed',0)} observerte varianter")
    if report.get("interpretation_status") == "READY" and report.get("ai_interpretation"):
        st.markdown(report["ai_interpretation"])
        st.caption("Research-notat fra AI. Hypoteser må verifiseres prospektivt. Ingen automatiske strategiendringer.")
    elif report.get("interpretation_status") == "AI_FAILED":
        st.warning("AI-analysen feilet. Faktagrunnlaget er bevart, men rapporten ble ikke generert.")
    else:
        st.caption(
            "Automatisk AI-rapport aktiveres når nok nye data finnes etter oppstart. "
            "Den analyserer kombinasjoner, forbedringer, nye idéer og tekniske regimer."
        )
    with st.expander("Se dokumentert datagrunnlag"):
        st.json(report)

st.caption(
    "Lab v1 · forskningssystem. Rangeringer alene er ikke statistisk evidens for "
    "fremtidig meravkastning; sammenlign kontroller, kostnader og fremtidige holdout-perioder."
)
