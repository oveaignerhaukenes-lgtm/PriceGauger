"""Dedicated full-width IC14 control surface; uses the existing per-instance settings."""
from datetime import datetime,timezone,timedelta
import streamlit as st
from database import connect
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_impulse_catcher_v14 import KEYS
from autotrader_ic14_ui import render_ic14

st.set_page_config(page_title="Signal Studio · IC v1.4",layout="wide",initial_sidebar_state="collapsed")
st.title("Signal Studio · Impulse Catcher v1.4")
st.caption("Full bredde · samme innstillinger som AutoTrader · ingen automatisk strategi- eller kontoaktivering")

instances=[i for i in load_v3_instances_v1() if i.uic==4912 and i.asset_type=="CfdOnIndex"]
if not instances:
    st.info("Ingen Tech100-instanser registrert i AutoTrader.")
    st.stop()

@st.cache_data(ttl=30,show_spinner=False)
def names():
    # Use stored account truth, never issue new Saxo API calls from the lab.
    with connect() as db:
        rows=db.execute("""SELECT account_id,account_name,observed_at FROM pg_saxo_account_truth_v1
            WHERE observed_at>=? ORDER BY observed_at DESC LIMIT 1000""",
            ((datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),)).fetchall()
    out={}
    for r in rows:
        out.setdefault(str(r["account_id"]),str(r["account_name"]))
    return out

try:
    labels=names()
except Exception:
    labels={}
configs={str(i.instance_id):load_autotrader_config_v3(str(i.instance_id)) for i in instances}
by_id={str(i.instance_id):i for i in instances}
ids=tuple(by_id)
preferred=st.session_state.pop("ic14:studio:requested_instance",None)
active=next((k for k in ids if configs[k].strategy_key in KEYS),ids[0])
if preferred in ids:
    st.session_state["ic14:studio:instance"]=preferred
selected=st.selectbox("Instans",ids,index=ids.index(active),
    format_func=lambda k: (labels.get(str(by_id[k].account_id)) or str(by_id[k].account_id))+
        " · "+configs[k].strategy_key,key="ic14:studio:instance")
current=configs[selected].strategy_key
keys=tuple(sorted(KEYS))
requested=st.session_state.pop("ic14:studio:requested_strategy",None)
variant=st.selectbox("IC v1.4 variant",keys,index=keys.index(current) if current in keys else 0,
    format_func=lambda k:"LONG / FLAT" if "-long-" in k else "SHORT / FLAT",
    key="ic14:studio:variant:"+selected)
if variant!=current:
    st.info("Du redigerer en ikke-valgt variant. Lagring her endrer kun dens egne parametere, ikke hvilken strategi som er aktiv.")
mode=st.radio("Arbeidsflate",["IC v1.4 · kontroll","Signalprosessering · eksperiment"],horizontal=True)
if mode=="IC v1.4 · kontroll":
    render_ic14(selected,variant,prefix="ic14-studio")
else:
    from signal_dsp_lab_ui_v1 import render_signal_dsp_lab
    render_signal_dsp_lab()
