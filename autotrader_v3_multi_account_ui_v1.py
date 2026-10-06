from __future__ import annotations

import streamlit as st

from autotrader_engine_account_ownership_v1 import load_account_owner_v1
from autotrader_v3_instance_binding_v1 import (
    load_available_v3_instrument_bindings_v1,
    replace_unarmed_v3_instance_binding_v1,
    same_v3_binding_v1,
)
from autotrader_v3_instance_registry_v1 import (
    bootstrap_v3_instances_from_enrollments_v1,
    create_v3_instance_v1,
)
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3


def _account_rows_v1(broker):
    rows=[]
    if broker is None:return rows
    try: raw=broker.accounts()
    except Exception:return rows
    for row in raw:
        if not isinstance(row,dict):continue
        aid=str(row.get('AccountId') or '').strip()
        if not aid:continue
        name=str(row.get('AccountName') or row.get('DisplayName') or '').strip()
        rows.append((aid,name))
    return rows


def render_v3_instance_selector_v1(*,key_prefix='v3-instance'):
    instances=bootstrap_v3_instances_from_enrollments_v1()
    if not instances:st.info('Ingen V3-instans finnes ennå.');return None
    broker=configured_live_pilot_client_v3()
    account_rows=_account_rows_v1(broker);account_names={aid:name for aid,name in account_rows}
    by_id={i.instance_id:i for i in instances}
    def instance_label(k):
        item=by_id[k];name=account_names.get(item.account_id,'')
        account=f'{name} ({item.account_id})' if name else item.account_id
        return f'{item.market_name} · {account} · UIC {item.uic}'
    ids=tuple(by_id)
    tab_key=f'{key_prefix}:tabs';pending_tab_key=f'{key_prefix}:pending-tab'
    pending_tab=st.session_state.pop(pending_tab_key,None)
    if pending_tab in by_id:st.session_state[tab_key]=pending_tab
    selected=st.radio('V3-instans',ids,format_func=instance_label,horizontal=True,key=tab_key)

    bindings=load_available_v3_instrument_bindings_v1()
    binding_by_key={item.key:item for item in bindings}

    with st.popover('＋ Legg til konto'):
        if broker is None:
            st.warning('Saxo LIVE er ikke tilgjengelig; kan ikke hente kontoer.')
        elif not account_rows:
            st.caption('Ingen Saxo-kontoer ble returnert.')
        elif not bindings:
            st.warning('Ingen canonical Saxo-instrumenter fra TradingDesk er tilgjengelige.')
        else:
            attached={i.account_id:i for i in instances};rows=[]
            for aid,name in account_rows:
                owner=load_account_owner_v1(aid);reason=None
                if aid in attached:reason=f'V3 {attached[aid].instance_id[:8]}'
                elif owner is not None:reason=f'{owner.engine_id} {owner.owner_key[:8]}'
                rows.append((aid,name,reason))
            options=tuple(a for a,_,_ in rows);meta={a:(n,r) for a,n,r in rows}
            def account_label(a):
                n,r=meta[a];base=f'{a}' + (f' · {n}' if n else '')
                return f'🔒 {base} · i bruk av {r}' if r else f'✓ {base} · ledig'
            account_id=st.selectbox('Saxo-konto',options,format_func=account_label,key=f'{key_prefix}:new-account')
            binding_key=st.selectbox(
                'Marked / instrument',
                tuple(binding_by_key),
                format_func=lambda k:binding_by_key[k].label,
                key=f'{key_prefix}:new-binding',
            )
            reason=meta[account_id][1];template=binding_by_key[binding_key]
            if reason:st.caption(f'Kontoen kan ikke velges: den er allerede knyttet til {reason}.')
            else:st.caption(f'Ny instans: {account_id} → {template.label}')
            if st.button('Opprett V3-instans',type='primary',disabled=bool(reason),key=f'{key_prefix}:create'):
                created=create_v3_instance_v1(account_id=account_id,template=template)
                st.session_state[pending_tab_key]=created.instance_id
                st.success(f'V3-instans opprettet: {account_id} → {template.market_name}.')
                st.rerun()

    current=by_id[selected]
    with st.expander('Marked / instrument for valgt instans',expanded=False):
        st.caption(f'Nå: {current.market_name} · konto {current.account_id} · UIC {current.uic} · {current.asset_type}')
        if not bindings:
            st.warning('Ingen canonical TradingDesk-instrumenter er tilgjengelige.')
        else:
            keys=tuple(binding_by_key)
            exact=next((k for k,v in binding_by_key.items() if same_v3_binding_v1(current,v)),None)
            index=keys.index(exact) if exact in keys else 0
            target_key=st.selectbox(
                'Tilknyt instansen til',
                keys,
                index=index,
                format_func=lambda k:binding_by_key[k].label,
                key=f'{key_prefix}:binding:{current.instance_id}',
            )
            target=binding_by_key[target_key];same=same_v3_binding_v1(current,target)
            st.caption('Bytte er bare tillatt når både LIVE og SIM er av, uten execution-ownership eller pending ordre.')
            if st.button('Bytt marked / instrument',disabled=same,key=f'{key_prefix}:replace:{current.instance_id}'):
                try:
                    created=replace_unarmed_v3_instance_binding_v1(current,target)
                except Exception as exc:
                    st.error(f'Kan ikke bytte tilknytning: {exc}')
                else:
                    st.session_state[pending_tab_key]=created.instance_id
                    st.success(f'Ny V3-instans er knyttet til {target.market_name} på konto {created.account_id}.')
                    st.rerun()
    return by_id[selected]
