from __future__ import annotations

import streamlit as st

from autotrader_engine_account_ownership_v1 import load_account_owner_v1
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1, create_v3_instance_v1
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3


def render_v3_instance_selector_v1(*, key_prefix: str = "v3-instance"):
    instances=bootstrap_v3_instances_from_enrollments_v1()
    if not instances:
        st.info("Ingen V3-instans finnes ennå.")
        return None
    by_id={item.instance_id:item for item in instances}
    labels={item.instance_id:f"{item.account_id} · {item.market_name}" for item in instances}
    ids=tuple(by_id)
    selected=st.radio("V3 konto",ids,format_func=lambda key:labels[key],horizontal=True,key=f"{key_prefix}:tabs")
    with st.popover("＋ Legg til konto"):
        broker=configured_live_pilot_client_v3()
        if broker is None:
            st.warning("Saxo LIVE er ikke tilgjengelig; kan ikke hente kontoer.")
        else:
            used={item.account_id for item in instances}
            candidates=[]
            for row in broker.accounts():
                if not isinstance(row,dict): continue
                account_id=str(row.get("AccountId") or "").strip()
                if not account_id or account_id in used: continue
                owner=load_account_owner_v1(account_id)
                if owner is None:
                    candidates.append(account_id)
            if not candidates:
                st.caption("Ingen ledig Saxo-konto. Kontoer som allerede eies av V2/V3 kan ikke legges til.")
            else:
                account_id=st.selectbox("Saxo-konto",tuple(candidates),key=f"{key_prefix}:new-account")
                template=by_id[selected]
                st.caption(f"Ny instans bruker samme instrument-boundary som denne fanen: {template.market_name} · UIC {template.uic}.")
                if st.button("Opprett V3-fane",type="primary",key=f"{key_prefix}:create"):
                    created=create_v3_instance_v1(account_id=account_id,template=template)
                    st.session_state[f"{key_prefix}:tabs"]=created.instance_id
                    st.success(f"V3-instans opprettet for {account_id}.")
                    st.rerun()
    return by_id[selected]
