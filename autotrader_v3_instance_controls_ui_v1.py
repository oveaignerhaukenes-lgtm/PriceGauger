from __future__ import annotations

"""One canonical UI surface for editing one V3 instance.

TradingDesk and fleet management render this same component. Durable config/policy is
owned by the engine instance, never by either page.
"""
import streamlit as st
from autotrader_v3_config_v1 import AutoTraderConfigV3,load_autotrader_config_v3,save_autotrader_config_v3
from autotrader_v3_instance_binding_v1 import remove_unarmed_v3_instance_v1
from autotrader_v3_control_plane_v1 import authority_state_v3,set_live_enabled_v3
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3,load_execution_policy_v3,save_execution_policy_v3
from autotrader_v3_cost_guard_v1 import assess_transaction_cost_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_registry_v1 import (
    CONTROL_MODES_V3, MODIFIERS_V3, REGIME_TIMEFRAMES_V3, STRATEGIES_V3, TIMEFRAMES_V3,
    LIVE_CONTROL_MODES_V3, LIVE_MODIFIERS_V3, LIVE_TIMEFRAMES_V3,
    live_config_issues_v3, sim_config_issues_v3,
)


@st.cache_data(ttl=30,show_spinner=False)
def _cost_guard_cached_v3(account_id:str,market_name:str,uic:int,asset_type:str):
    broker=configured_live_pilot_client_v3()
    return assess_transaction_cost_v3(
        broker=broker,
        account_id=account_id,
        market_name=market_name,
        uic=int(uic),
        asset_type=asset_type,
    )


def _render_cost_guard_v3(assessment):
    max_cost=assessment.max_total_cost_pct
    commission=max(
        value for value in (assessment.long_commission,assessment.short_commission)
        if value is not None
    ) if any(value is not None for value in (assessment.long_commission,assessment.short_commission)) else None
    extra=[]
    if commission is not None:
        extra.append(f'maks kurtasje {commission:,.2f} {assessment.commission_currency or ""}'.strip())
    if max_cost is not None:
        extra.append(f'inn/ut {max_cost:.2f}%')
    text='Kostnadssjekk: '+assessment.detail
    if extra:
        text += ' · ' + ' · '.join(extra)
    if assessment.severity=='GREEN':
        st.success(text)
    elif assessment.severity=='YELLOW':
        st.warning(text)
    else:
        st.error(text)
    if assessment.assumptions:
        st.caption('Saxo cost assumptions: '+', '.join(assessment.assumptions))


def render_v3_instance_controls_v1(instance,*,key_prefix:str='v3-instance'):
    trader_id=str(instance.instance_id); config=load_autotrader_config_v3(trader_id); policy=load_execution_policy_v3(trader_id); authority=authority_state_v3(trader_id)
    st.markdown(f'**{instance.market_name} · konto {instance.account_id} · UIC {instance.uic}**')
    st.caption(f'V3 {trader_id[:8]} · {instance.asset_type} · instrument {instance.instrument_id} · config deles mellom TradingDesk og fleet-visningen')
    keys=tuple(x.key for x in STRATEGIES_V3)
    a,b=st.columns(2)
    strategy=a.selectbox(
        'Strategi', keys, index=keys.index(config.strategy_key),
        format_func=lambda k: next(x.label for x in STRATEGIES_V3 if x.key==k)
            + ('' if next(x for x in STRATEGIES_V3 if x.key==k).runtime_ready else ' · ikke LIVE'),
        key=f'{key_prefix}:strategy:{trader_id}',
    )
    timeframe=b.selectbox(
        'Signalperiode (S)', TIMEFRAMES_V3, index=TIMEFRAMES_V3.index(config.timeframe),
        format_func=lambda value: value if value in LIVE_TIMEFRAMES_V3 else f'{value} · ikke LIVE',
        key=f'{key_prefix}:timeframe:{trader_id}',
    )
    regime_timeframe=config.regime_timeframe
    if strategy=='macd-regime-histogram':
        regime_timeframe=st.selectbox(
            'Regimeperiode (R)',
            REGIME_TIMEFRAMES_V3,
            index=REGIME_TIMEFRAMES_V3.index(config.regime_timeframe),
            key=f'{key_prefix}:regime-timeframe:{trader_id}',
            help='MACD på R-perioden bestemmer tillatt side. Histogram på S-perioden bygger/reduserer eksponeringen.',
        )
        st.caption(f'Aktiv modell: Histogram MACD-R{regime_timeframe}S{timeframe}')
    spec=next(x for x in STRATEGIES_V3 if x.key==strategy)
    if not spec.runtime_ready: st.warning('Denne strategien er SIM/sammenlignbar, men ikke runtime-klar for LIVE.')
    p1,p2=st.columns(2); budget=p1.number_input('Budsjett (NOK)',min_value=100.0,value=float(policy.budget_nok if policy else 2000),step=100.0,key=f'{key_prefix}:budget:{trader_id}'); exposure=p2.slider('Eksponering (%)',1,100,int(policy.exposure_pct if policy else 100),key=f'{key_prefix}:exposure:{trader_id}')
    st.caption(f'LIVE kapitalgrense: {float(budget)*float(exposure)/100.0:,.0f} NOK · håndheves mot Saxo precheck (margin/cash).')
    st.markdown('**Options / modifiers**'); enabled=[]; cols=st.columns(3)
    for n,item in enumerate(MODIFIERS_V3):
        label=item.label if item.key in LIVE_MODIFIERS_V3 else f'{item.label} · ikke LIVE'
        help_text=item.description + ('' if item.key in LIVE_MODIFIERS_V3 else ' Lagres for V3/SIM, men er ikke koblet til LIVE-runtime ennå.')
        if cols[n%3].toggle(label,value=item.key in config.modifiers,key=f'{key_prefix}:mod:{trader_id}:{item.key}',help=help_text):
            enabled.append(item.key)
    mode=st.selectbox(
        'Kontrollmodus', CONTROL_MODES_V3, index=CONTROL_MODES_V3.index(config.control_mode),
        format_func=lambda value: value if value in LIVE_CONTROL_MODES_V3 else f'{value} · ikke LIVE',
        key=f'{key_prefix}:mode:{trader_id}',
    )
    desired=AutoTraderConfigV3(
        trader_id,strategy,timeframe,mode,tuple(enabled),regime_timeframe
    ); desired_policy=ExecutionPolicyV3(trader_id,float(budget),float(exposure)); changed=desired!=config or desired_policy!=policy
    live_issues=live_config_issues_v3(
        strategy_key=desired.strategy_key,timeframe=desired.timeframe,
        control_mode=desired.control_mode,modifiers=desired.modifiers,
        regime_timeframe=desired.regime_timeframe,
    )
    sim_issues=sim_config_issues_v3(
        strategy_key=desired.strategy_key,timeframe=desired.timeframe,
        control_mode=desired.control_mode,modifiers=desired.modifiers,
        regime_timeframe=desired.regime_timeframe,
    )
    if live_issues:
        st.warning('LIVE sperret av config: ' + ' · '.join(live_issues))
    cost_assessment=_cost_guard_cached_v3(
        str(instance.account_id),str(instance.market_name),int(instance.uic),str(instance.asset_type))
    _render_cost_guard_v3(cost_assessment)
    cost_blocked=bool(cost_assessment.blocked)
    if sim_issues:
        st.info('SIM sperret av config: ' + ' · '.join(sim_issues))
    save_blocked=bool((authority.live_armed and live_issues) or (authority.sim_armed and sim_issues))
    if save_blocked:
        st.caption('Slå den aktive motoren av før du lagrer en config som den ikke støtter.')
    if st.button('Bruk på denne instansen',type='primary',disabled=(not changed or save_blocked),width='stretch',key=f'{key_prefix}:save:{trader_id}'):
        save_autotrader_config_v3(desired); save_execution_policy_v3(desired_policy); st.success('Canonical V3 config oppdatert.'); st.rerun()

    st.markdown('**Execution authority**')
    if authority.live_armed:
        st.success(f'LIVE PÅ · konto {instance.account_id} · UIC {instance.uic}')
        if st.button('Slå LIVE av',width='stretch',key=f'{key_prefix}:live-off:{trader_id}'):
            try:set_live_enabled_v3(trader_id,False,account_id=instance.account_id)
            except Exception as exc:st.error(f'Kunne ikke slå LIVE av: {exc}')
            else:st.rerun()
    else:
        st.caption('LIVE AV · knappen under gir denne V3-instansen execution-authority på eksakt konto/instrument.')
        if st.button('Slå LIVE på',type='primary',width='stretch',disabled=bool(live_issues or cost_blocked),key=f'{key_prefix}:live-on:{trader_id}'):
            try:
                fresh_cost=assess_transaction_cost_v3(
                    broker=configured_live_pilot_client_v3(),
                    account_id=str(instance.account_id),
                    market_name=str(instance.market_name),
                    uic=int(instance.uic),
                    asset_type=str(instance.asset_type),
                )
                if fresh_cost.blocked:
                    raise RuntimeError(f'LIVE kostnadssperre: {fresh_cost.detail}')
                if changed:
                    save_autotrader_config_v3(desired); save_execution_policy_v3(desired_policy)
                set_live_enabled_v3(trader_id,True,account_id=instance.account_id)
            except Exception as exc:st.error(f'Kunne ikke slå LIVE på: {exc}')
            else:st.rerun()

    st.divider()
    st.markdown('**Instans**')
    st.caption('Fjerning deaktiverer bare instansen i fleet-listen. Historikk, config og execution-audit beholdes.')
    if st.button(
        'Fjern fra AutoTrader',
        width='stretch',
        disabled=bool(authority.live_armed or authority.sim_armed),
        key=f'{key_prefix}:remove:{trader_id}',
        help='LIVE og SIM må være AV. Uavklart ordre eller execution-ownership blokkerer også fjerning.',
    ):
        try:
            remove_unarmed_v3_instance_v1(instance)
        except Exception as exc:
            st.error(f'Kunne ikke fjerne instansen: {exc}')
        else:
            st.success('V3-instansen er fjernet fra aktiv fleet. Historikken er beholdt.')
            st.rerun()

__all__=['render_v3_instance_controls_v1']
