"""Read-only V3 account/fleet operational observer dashboard."""
from __future__ import annotations

from collections import Counter
import pandas as pd
import streamlit as st

from autotrader_v3_fleet_observer_v1 import load_monitor_rows,run_monitor_once
from autotrader_account_learning_v1 import load_account_learning_findings_v1
from autotrader_v3_registry_v1 import MODIFIERS_V3,LIVE_MODIFIERS_V3

st.title("AutoTrader · Observatør")
st.info("Første versjon: Kjør «Oppdater operativ vurdering nå». Bakgrunnsovervåking er ennå ikke aktivert.")
st.caption(
    "Én operativ observatør per LIVE-aktiv, V3-eid konto og en samlet "
    "flåteoversikt. Manuell databasekontroll (automatisk minuttscheduler ikke koblet til ennå), ingen Saxo ordre "
    "eller automatisk strategiendring. Konto-læring analyserer separat "
    "bekreftede 5-minutters NAV-observasjoner."
)
try:
    records=load_monitor_rows(limit=350)
except Exception as exc:
    st.error("Observatørhistorikk utilgjengelig: "+type(exc).__name__)
    st.stop()
if st.button("Oppdater operativ vurdering nå (kun database)"):
    try:
        run_monitor_once()
        records=load_monitor_rows(limit=350)
    except Exception as exc:
        st.error("Klarte ikke oppdatere: "+type(exc).__name__)
latest={}
for item in records:
    latest.setdefault(str(item["instance_id"]),item)
current=tuple(latest.values())
counts=Counter(str(item["severity"]) for item in current)
a,b,c,d=st.columns(4)
a.metric("Aktive V3-observatører",len(current))
b.metric("OK",counts["OK"])
c.metric("Varsel",counts["WARNING"])
d.metric("Kritisk",counts["CRITICAL"])
if not current:
    st.info("Ingen observerte aktive instanser ennå. Start worker-telemetrien.")
else:
    st.dataframe(pd.DataFrame([{
        "Instans":str(x["instance_id"])[:8],
        "Strategi":x["strategy_key"],
        "Tilstand":x["severity"],
        "Runtime":x["status"],
        "Bekreftede handler 15m":x["fill_count"],
        "Problem/undersøkelse":x["signal"],
        "Sist observert":x["observed_minute"],
    } for x in current]),hide_index=True,use_container_width=True)
    duplicates=Counter(x["strategy_key"] for x in current)
    same={key:count for key,count in duplicates.items() if count>1}
    if same:
        st.info(
            "Felles eksponering: "+", ".join(f"{key} ×{n}" for key,n in same.items())+
            ". Samme strategi på flere kontoer er ikke uavhengig diversifisering."
        )
    pick=st.selectbox("Undersøk V3-instans",tuple(latest),
        format_func=lambda key:f"{latest[key]['strategy_key']} · {key[:8]}")
    chosen=latest[pick]
    st.subheader("Observasjonshistorikk")
    rows=[x for x in records if x["instance_id"]==pick][:100]
    st.dataframe(pd.DataFrame(rows)[["observed_minute","severity","status",
        "signal","fill_count"]],hide_index=True,use_container_width=True)
    st.subheader("Observerte forbedringshypoteser")
    try:
        findings=load_account_learning_findings_v1(account_id=chosen["account_id"],limit=30)
    except Exception:
        findings=()
    if findings:
        for x in findings[:12]:
            if x["instance_id"]!=pick:
                continue
            with st.expander(f"{x['last_observed']} · {x['title']}"):
                st.write(x["hypothesis"])
                st.write("PAPER A/B-forslag: "+x["test_plan"])
                st.caption("Forskningshypotese, ikke dokumentert nettoprofitt")
    else:
        st.caption("Ingen konto-læringshypoteser ennå.")

st.subheader("LIVE-modifikatorer · statuskontroll")
st.caption(
    "LIVE-klar betyr at det finnes en sikker kodebane i V3. Det betyr "
    "ikke at funksjonen er aktivert, har demonstrert forbedring eller "
    "at risikoen for store tap er eliminert."
)
specs=[]
notes={
    "reset-on-loss":"Saxo åpen P/L; sender FLAT ved negativ åpen P/L",
    "whipsaw":"LIVE-kode med egen instansgodkjenning; stopper OPEN/ADD",
    "volatility-pause":"LIVE-kode; stopper OPEN/ADD ved høy 1m-volatilitet",
    "ai-loss-manager":"LIVE-kode krever fersk godkjent SHADOW-AI og konto-P/L",
    "impulse-exit":"LIVE-kode; 10s BBO-motimpuls, FLAT + cooldown",
    "account-loss-lock":"LIVE-kode; Saxo NAV, 10% lås, ikke kontantstrømjustert",
}
for mod in MODIFIERS_V3:
    supported=mod.key in LIVE_MODIFIERS_V3
    specs.append({
        "Modifikator":mod.label,
        "LIVE":("JA · betinget" if mod.key in ("whipsaw","ai-loss-manager")
                else "JA" if supported else "NEI · sperret"),
        "Hva er bekreftet":notes.get(mod.key,
            "Katalog/konsept; ingen verifisert V3 LIVE-implementasjon"),
    })
st.dataframe(pd.DataFrame(specs),hide_index=True,use_container_width=True)
st.warning(
    "Observatørens runtime-/ordreadvarsler er ikke handelsordre. "
    "Manglende logghendelser alene beviser ikke at en modifikator er defekt. "
    "NAV er ikke justert for kontantstrømmer, manuelle handler, funding og FX."
)
