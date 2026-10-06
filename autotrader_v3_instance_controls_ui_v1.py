from __future__ import annotations

"""One canonical UI surface for editing one V3 instance.

TradingDesk and fleet management render this same component. Durable config/policy is
owned by the engine instance, never by either page.
"""
import streamlit as st
from autotrader_v3_config_v1 import AutoTraderConfigV3,load_autotrader_config_v3,save_autotrader_config_v3
from autotrader_v3_control_plane_v1 import authority_state_v3,set_live_enabled_v3
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3,load_execution_policy_v3,save_execution_policy_v3
from autotrader_v3_registry_v1 import CONTROL_MODES_V3,MODIFIERS_V3,STRATEGIES_V3,TIMEFRAMES_V3


def render_v3_instance_controls_v1(instance,*,key_prefix:str='v3-instance'):
    trader_id=str(instance.instance_id); config=load_autotrader_config_v3(trader_id); policy=load_execution_policy_v3(trader_id)
    st.markdown(f'**{instance.market_name} · konto {instance.account_id} · UIC {instance.uic}**')
    st.caption(f'V3 {trader_id[:8]} · {instance.asset_type} · instrument {instance.instrument_id} · config deles mellom TradingDesk og fleet-visningen')
    keys=tuple(x.key for x in STRATEGIES_V3)
    a,b=st.columns(2)
    strategy=a.selectbox('Strategi',keys,index=keys.index(config.strategy_key),format_func=lambda k:next(x.label for x in STRATEGIES_V3 if x.key==k),key=f'{key_prefix}:strategy:{trader_id}')
    timeframe=b.selectbox('Periode',TIMEFRAMES_V3,index=TIMEFRAMES_V3.index(config.timeframe),key=f'{key_prefix}:timeframe:{trader_id}')
    spec=next(x for x in STRATEGIES_V3 if x.key==strategy)
    if not spec.runtime_ready: st.warning('Denne strategien er SIM/sammenlignbar, men ikke runtime-klar for LIVE.')
    p1,p2=st.columns(2); budget=p1.number_input('Budsjett (NOK)',min_value=100.0,value=float(policy.budget_nok if policy else 2000),step=100.0,key=f'{key_prefix}:budget:{trader_id}'); exposure=p2.slider('Eksponering (%)',1,100,int(policy.exposure_pct if policy else 100),key=f'{key_prefix}:exposure:{trader_id}')
    st.markdown('**Options / modifiers**'); enabled=[]; cols=st.columns(3)
    for n,item in enumerate(MODIFIERS_V3):
        if cols[n%3].toggle(item.label,value=item.key in config.modifiers,key=f'{key_prefix}:mod:{trader_id}:{item.key}',help=item.description): enabled.append(item.key)
    mode=st.selectbox('Kontrollmodus',CONTROL_MODES_V3,index=CONTROL_MODES_V3.index(config.control_mode),key=f'{key_prefix}:mode:{trader_id}')
    desired=AutoTraderConfigV3(trader_id,strategy,timeframe,mode,tuple(enabled)); desired_policy=ExecutionPolicyV3(trader_id,float(budget),float(exposure)); changed=desired!=config or desired_policy!=policy
    if st.button('Bruk på denne instansen',type='primary',disabled=not changed,width='stretch',key=f'{key_prefix}:save:{trader_id}'):
        save_autotrader_config_v3(desired); save_execution_policy_v3(desired_policy); st.success('Canonical V3 config oppdatert.'); st.rerun()

    authority=authority_state_v3(trader_id)
    st.markdown('**Execution authority**')
    if authority.live_armed:
        st.success(f'LIVE PÅ · konto {instance.account_id} · UIC {instance.uic}')
        if st.button('Slå LIVE av',width='stretch',key=f'{key_prefix}:live-off:{trader_id}'):
            try:set_live_enabled_v3(trader_id,False,account_id=instance.account_id)
            except Exception as exc:st.error(f'Kunne ikke slå LIVE av: {exc}')
            else:st.rerun()
    else:
        st.caption('LIVE AV · knappen under gir denne V3-instansen execution-authority på eksakt konto/instrument.')
        if st.button('Slå LIVE på',type='primary',width='stretch',disabled=not spec.runtime_ready,key=f'{key_prefix}:live-on:{trader_id}'):
            try:
                if changed:
                    save_autotrader_config_v3(desired); save_execution_policy_v3(desired_policy)
                set_live_enabled_v3(trader_id,True,account_id=instance.account_id)
            except Exception as exc:st.error(f'Kunne ikke slå LIVE på: {exc}')
            else:st.rerun()

__all__=['render_v3_instance_controls_v1']
