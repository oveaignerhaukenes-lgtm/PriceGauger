"""Choose a Saxo account to follow; read-only learning journal and test ideas."""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from autotrader_saxo_account_truth_v1 import load_account_truth_v1
from autotrader_saxo_strategy_timeline_v1 import (
    observed_live_nav_windows_v1,
)
from autotrader_account_learning_v1 import (
    load_account_learning_watches_v1,load_account_learning_findings_v1,
    load_account_learning_executions_v1,set_account_learning_watch_v1,
    run_account_learning_cycle_v1,
)
from datetime import datetime,timezone

st.title("Konto-læring · Observatør")
st.caption(
    "Velg en Saxo-konto. Når observasjon er PÅ, følger en egen worker "
    "kontoens bekreftede kontoverdier, V3-ordrer og tidslåst strategikontekst "
    "og lagrer mulige forbedringer til SIM A/B. "
    "Ingen strategi, konto eller ordretillatelse endres automatisk."
)
st.warning(
    "Endring i Saxo TotalValue er uavstemt kontoverdi – IKKE dokumentert "
    "strategi-P/L. Innskudd/uttak, manuelle handler, FX og finansieringskostnader "
    "må avstemmes før reelle resultatkonklusjoner."
)
try:
    all_samples=load_account_truth_v1(days=30)
    watches={str(r["account_id"]):bool(r["enabled"])
             for r in load_account_learning_watches_v1()}
except Exception as exc:
    st.error("Læringsdata ikke tilgjengelig: "+type(exc).__name__)
    st.stop()
if not all_samples:
    st.info("Ingen Saxo-kontomålinger finnes ennå. Konto-innsamlingen må starte før du kan velge.")
    st.stop()

newest={}
for row in all_samples:
    aid=str(row["account_id"])
    newest[aid]=row
labels={
    f"{v['account_name']} · {v['currency']} [{aid[-5:]}]":aid
    for aid,v in newest.items()
}
choice=st.selectbox("Velg kontoen læringsmotoren skal følge",
                    options=tuple(labels),key="learning-account-picker")
account=labels[choice]
latest=newest[account]
selected_samples=tuple(x for x in all_samples
                       if str(x["account_id"])==account)
tracked=bool(watches.get(account,False))
enabled=st.toggle("Følg kontoen automatisk hvert femte minutt",
                  value=tracked,key=f"learning-follow:{account}")
if enabled!=tracked:
    try:
        set_account_learning_watch_v1(account_id=account,enabled=enabled)
        st.success("Observasjon aktivert." if enabled else "Observasjon pauset.")
    except Exception as exc:
        st.error("Kunne ikke lagre kontovalg: "+type(exc).__name__)

value=float(latest["total_value"])
currency=str(latest["currency"])
a,b,c=st.columns(3)
a.metric("Saxo TotalValue",f"{value:,.2f} {currency}")
b.metric("Verifiserbarhet",str(latest["calculation_reliability"]))
c.metric("Overvåking","PÅ" if enabled else "AV")
if value<=0:
    st.info("Kontoen ser ut til å være ufinansiert. Den kan velges, men "
            "læringsmotoren vil ikke trekke strategikonklusjoner uten "
            "verifisert kontoaktivitet.")
st.caption("Kontodata oppdateres via Saxo GET i en separat femminuttsworker. "
           "Siden trenger ikke stå åpen.")

if st.button("Analyser lagrede målinger nå (ingen Saxo-ordre)",
             key="learning-evaluate"):
    with st.spinner("Kobler sammen Saxo NAV, kontekst og bekreftede V3-ordre ..."):
        try:
            outcome=run_account_learning_cycle_v1()
        except Exception as exc:
            st.error("Analyse ikke tilgjengelig: "+type(exc).__name__)
        else:
            st.info(f"Fulgte kontoer: {outcome['watched_accounts']} · "
                    f"målinger: {outcome['samples']} · "
                    f"nye forskningshypoteser: {outcome['new_findings']} · "
                    f"feil: {outcome['errors']}.")
verified=tuple(x for x in selected_samples
               if str(x.get("calculation_reliability","")).lower()=="ok"
               and float(x["total_value"])>0)
st.subheader("Saxo-kontoverdi · observerte målinger")
if verified:
    values=pd.DataFrame(verified)
    values["observed_at"]=pd.to_datetime(values["observed_at"],utc=True)
    values=values.drop_duplicates("observed_at").set_index("observed_at")
    st.line_chart(values[["total_value"]].rename(columns={
        "total_value":f"Saxo TotalValue ({currency})"}),use_container_width=True)
else:
    st.info("Ingen verifiserte målinger på denne kontoen i valgt periode.")

st.subheader("Strategiperioder · kun observert samtidighet")
try:
    windows=observed_live_nav_windows_v1(selected_samples)
except (ValueError,KeyError,TypeError):
    windows=()
if windows:
    st.dataframe(pd.DataFrame([
        {"Fra UTC":w.first_observed,"Til UTC":w.last_observed,
         "Strategi":w.strategy_key,"Tidsramme":w.timeframe,
         "Marked":w.market,"Målinger":w.observations,
         f"NAV-endring {currency} (uavstemt)":w.value_change,
         "NAV-endring % (uavstemt)":w.value_change_pct,
         "Maks observert NAV-trekk %":w.max_observed_drawdown_pct}
        for w in windows[-60:]
    ]).iloc[::-1],use_container_width=True,hide_index=True)
else:
    st.caption("Ingen sammenhengende, verifiserte LIVE-strategiperioder ennå.")

st.subheader("Bekreftede V3-ordrehendelser")
try:
    since=min(datetime.fromisoformat(str(x["observed_at"]).replace("Z","+00:00"))
              for x in selected_samples)
    events=load_account_learning_executions_v1(account_id=account,since=since)
except Exception:
    events=None
if events is None:
    st.warning("Ordreloggen er utilgjengelig. Fravær av registrerte ordre kan ikke antas.")
elif events:
    st.dataframe(pd.DataFrame([{
        "Tid UTC":e["executed_at"],"Instans":e["instance_id"],
        "Marked":e["market_name"],"Handling":e["action"],
        "Side":e["side"],"Lot":e["amount"],
        "Etter (lot)":e["inventory_after"],
    } for e in events[-100:]]).iloc[::-1],use_container_width=True,hide_index=True)
else:
    st.caption("Ingen bekreftede V3-ordre registrert i kontoperioden.")

st.subheader("Læringsjournal · foreslåtte forbedringer")
findings=load_account_learning_findings_v1(account_id=account)
if not findings:
    st.info("Ingen hypoteser ennå. Motoren krever minst fire sammenhengende "
            "verifiserte 5m-målinger, entydig LIVE-strategi og relevant evidence. "
            "Ufinansierte kontoer og manglende data gir ikke falske funn.")
for item in findings[:40]:
    with st.expander(
        f"{str(item['last_observed'])[:16]} · {item['title']} "
        f"· {item['strategy_key']}",expanded=False
    ):
        st.markdown("**Observerbar hypotese:** "+str(item["hypothesis"]))
        st.markdown("**SIM A/B / kontroll:** "+str(item["test_plan"]))
        data=json.loads(item["evidence_json"])
        st.caption("Status: forskningsforslag, ikke demonstrert forbedring. "
                   "Ingen LIVE-autorisasjon.")
        st.json({k:v for k,v in data.items()
                 if k not in ("account_id","instance_id")})
