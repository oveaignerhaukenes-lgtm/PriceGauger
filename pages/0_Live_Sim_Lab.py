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
    "Sim-handler": row["trades"], "Siste datapunkt": row["last_bar"] or "Ingen",
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
