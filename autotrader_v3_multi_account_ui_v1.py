from __future__ import annotations
import streamlit as st
from autotrader_engine_account_ownership_v1 import load_account_owner_v1
from autotrader_v3_instance_registry_v1 import bootstrap_v3_instances_from_enrollments_v1,create_v3_instance_v1
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3

def render_v3_instance_selector_v1(*,key_prefix='v3-instance'):
    instances=bootstrap_v3_instances_from_enrollments_v1()
    if not instances:st.info('Ingen V3-instans finnes ennå.');return None
    by_id={i.instance_id:i for i in instances};labels={i.instance_id:f'{i.account_id} · {i.market_name}' for i in instances};ids=tuple(by_id)
    tab_key=f'{key_prefix}:tabs';pending_tab_key=f'{key_prefix}:pending-tab'
    pending_tab=st.session_state.pop(pending_tab_key,None)
    if pending_tab in by_id:st.session_state[tab_key]=pending_tab
    selected=st.radio('V3 konto',ids,format_func=lambda k:labels[k],horizontal=True,key=tab_key)
    with st.popover('＋ Legg til konto'):
        broker=configured_live_pilot_client_v3()
        if broker is None:st.warning('Saxo LIVE er ikke tilgjengelig; kan ikke hente kontoer.')
        else:
            attached={i.account_id:i for i in instances};rows=[]
            for row in broker.accounts():
                if not isinstance(row,dict):continue
                aid=str(row.get('AccountId') or '').strip()
                if not aid:continue
                owner=load_account_owner_v1(aid);reason=None
                if aid in attached:reason=f'V3 {attached[aid].instance_id[:8]}'
                elif owner is not None:reason=f'{owner.engine_id} {owner.owner_key[:8]}'
                name=str(row.get('AccountName') or row.get('DisplayName') or '').strip()
                rows.append((aid,name,reason))
            if not rows:st.caption('Ingen Saxo-kontoer ble returnert.')
            else:
                options=tuple(a for a,_,_ in rows);meta={a:(n,r) for a,n,r in rows}
                def label(a):
                    n,r=meta[a];base=f'{a}' + (f' · {n}' if n else '')
                    return f'🔒 {base} · i bruk av {r}' if r else f'✓ {base} · ledig'
                account_id=st.selectbox('Saxo-konto',options,format_func=label,key=f'{key_prefix}:new-account')
                reason=meta[account_id][1];template=by_id[selected]
                if reason:st.caption(f'Kontoen kan ikke velges: den er allerede knyttet til {reason}.')
                else:st.caption(f'Ny instans bruker instrumentet fra valgt fane: {template.market_name} · UIC {template.uic}.')
                if st.button('Opprett V3-instans',type='primary',disabled=bool(reason),key=f'{key_prefix}:create'):
                    created=create_v3_instance_v1(account_id=account_id,template=template);st.session_state[pending_tab_key]=created.instance_id;st.success(f'V3-instans opprettet for {account_id}.');st.rerun()
    return by_id[selected]
