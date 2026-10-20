from __future__ import annotations

"""One canonical UI surface for editing one V3 instance.

TradingDesk and fleet management render this same component. Durable config/policy is
owned by the engine instance, never by either page.
"""
import streamlit as st
from autotrader_v3_config_v1 import AutoTraderConfigV3,load_autotrader_config_v3,save_autotrader_config_v3
from autotrader_v3_ai_live_presets_v1 import (
    AI_LIVE_PRESETS_V3,PRESETS_BY_KEY_V3,initial_selector_key_v3,
    resolve_selector_draft_v3,ai_preset_selected_v3,
)
from autotrader_v3_instance_binding_v1 import remove_unarmed_v3_instance_v1
from autotrader_v3_control_plane_v1 import authority_state_v3,set_live_enabled_v3
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3,load_execution_policy_v3,save_execution_policy_v3
from autotrader_v3_cost_guard_v1 import assess_transaction_cost_v3
from autotrader_v3_whipsaw_live_v1 import is_whipsaw_live_approved_v3,set_whipsaw_live_approval_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_live_truth_v1 import inventory_label_v1,load_v3_live_truth_v1
from autotrader_v3_registry_v1 import (
    CONTROL_MODES_V3, MODIFIERS_V3, REGIME_STRATEGIES_V3, REGIME_TIMEFRAMES_V3, STRATEGIES_V3, TIMEFRAMES_V3,
    LIVE_CONTROL_MODES_V3, LIVE_MODIFIERS_V3, LIVE_TIMEFRAMES_V3,
    live_config_issues_v3, sim_config_issues_v3, strategy_display_label_v3,
)


RHYTHM_1M_CATALOG_KEYS_V3 = frozenset((
    'macd-stoch-rhythm-build', 'rhythm-trend-1',
    'rhythm-build-fractal', 'rhythm-trend-fractal',
))
RHYTHM_R15_CATALOG_KEYS_V3 = frozenset((
    'rhythm-trend-1', 'rhythm-trend-fractal',
))


def _rhythm_selection_defaults_v3(previous_strategy: str, selected_strategy: str) -> dict[str, str]:
    """On an explicit strategy switch, propose valid periods without mutating saved config."""
    if previous_strategy == selected_strategy or selected_strategy not in RHYTHM_1M_CATALOG_KEYS_V3:
        return {}
    selected = {'timeframe': '1m'}
    if selected_strategy in RHYTHM_R15_CATALOG_KEYS_V3:
        selected['regime_timeframe'] = '15m'
    return selected


def _instance_save_blocked_v3(*, live_armed: bool, sim_armed: bool,
                               live_issues, sim_issues) -> bool:
    """SIM-only limitations cannot prevent saving an otherwise LIVE-valid config.

    If SIM is armed with an incompatible config it is independently denied by
    the SIM worker; this never authorizes an unsupported LIVE configuration.
    """
    return bool((live_armed and live_issues) or
                (sim_armed and sim_issues and live_issues))


@st.cache_data(ttl=30,show_spinner=False)
def _account_name_cached_v3(account_id:str)->str:
    broker=configured_live_pilot_client_v3()
    if broker is None:
        return ""
    try:
        for row in broker.accounts():
            if not isinstance(row,dict):
                continue
            if str(row.get("AccountId") or "").strip()==str(account_id).strip():
                return str(row.get("AccountName") or row.get("DisplayName") or "").strip()
    except Exception:
        return ""
    return ""


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
    account_name=_account_name_cached_v3(str(instance.account_id))
    account_title=account_name or str(instance.account_id)
    active_label=strategy_display_label_v3(config.strategy_key,config.timeframe,config.regime_timeframe)
    st.markdown(f'### {account_title} · {instance.market_name}')
    st.caption(
        f'Aktiv nå: {active_label} · konto {instance.account_id} · UIC {instance.uic} · '
        f'V3 {trader_id[:8]} · {instance.asset_type} · instrument {instance.instrument_id}'
    )
    truth=load_v3_live_truth_v1(
        instance_id=trader_id,account_id=str(instance.account_id),
        uic=int(instance.uic),asset_type=str(instance.asset_type))
    st.markdown('**LIVE-tilstand · sist lagret, kun lesing**')
    cap_label=f'{policy.max_notional_nok:,.0f} NOK' if policy else 'ikke satt'
    st.caption(
        f'Worker: {truth.status} · faktisk {inventory_label_v1(truth.actual)} · '
        f'mål {inventory_label_v1(truth.target)} · '
        f'kapitalramme {cap_label}'
        + (f' · oppdatert {truth.updated_at}' if truth.updated_at else ' · heartbeat mangler')
    )
    if truth.status.upper()=='BLOCKED' or 'grense' in truth.reason.casefold():
        st.warning(truth.reason + (f' · {truth.detail}' if truth.detail else ''))
    else:
        st.caption(truth.reason + (f' · {truth.detail}' if truth.detail else ''))
    st.caption('Siste bekreftede handel: '+(truth.last_execution or 'ingen tilgjengelig i eventloggen'))
    st.caption('Tallene er forrige worker-heartbeat, ikke en sanntids-Saxo-posisjonsforespørsel.')
    with st.expander('Unngå tap V1 · Saxo datakontroll (kun lesing)',expanded=False):
        st.caption(
            'Kontroller eksakt konto og instrument mot Saxo LIVE med kun GET. '
            'Rapporterer faste felt- og feilkoder uten konto-ID, beløp eller '
            'posisjonsidentifikatorer. Ingen handler, ordre-precheck, '
            'lagring eller aktivering. En vellykket kontroll gir IKKE LIVE-tillatelse.'
        )
        if st.button(
            'Les og valider Saxo-feltene nå',
            key=f'{key_prefix}:avoid-loss-readonly:{trader_id}',
        ):
            try:
                from autotrader_v3_avoid_loss_diagnostics_v1 import diagnose_saxo_avoid_loss_v1
                report=diagnose_saxo_avoid_loss_v1(
                    broker=configured_live_pilot_client_v3(),
                    account_id=str(instance.account_id),
                    uic=int(instance.uic),
                    asset_type=str(instance.asset_type),
                )
                st.write(f'**{report.status}** · {report.phase} · {report.code}')
                st.caption(
                    'Verifiserte felt: ' +
                    (', '.join(report.observed) if report.observed else 'ingen')
                )
                st.caption('LIVE-gate: LUKKET. Dette er kun en skrivebeskyttet diagnose.')
            except Exception as exc:
                st.error(
                    'Saxo-diagnosen ble avbrutt: '+type(exc).__name__
                    +' (ingen ordre eller endringer utført).'
                )
    st.caption(
        "Forsøksoppsett: Fast Exit S10/R30 + Volatility Pause er inspirert "
        "av LAB-varianten, men LIVE-motoren bruker Aen#2.1 Fast Exit og "
        "er ikke en matematisk identisk LAB-strategi."
    )
    if st.button(
        "Forhåndsvelg Fast Exit S10/R30 + Volatility Pause",
        key=f'{key_prefix}:preset-fast-exit-10-30:{trader_id}',
        help="Setter bare verdier i skjemaet. Ingen LIVE-konfigurasjon "
             "lagres, og ingen ordrer opprettes uten et separat lagreklikk.",
    ):
        st.session_state[f'{key_prefix}:strategy:{trader_id}']='aen21-sticky-fast-exit'
        st.session_state[f'{key_prefix}:timeframe:{trader_id}']='10m'
        st.session_state[f'{key_prefix}:regime-timeframe:{trader_id}']='30m'
        st.session_state[f'{key_prefix}:mod:{trader_id}:volatility-pause']=True
        st.rerun()
    st.caption("MACD Flip · V3 er separat fra MACD Trailing · Legacy og følger V2s rene kryss-signaler. Valg eller lagring alene aktiverer ikke LIVE.")
    st.caption("AEn Core: fem valgbare V3 LIVE-varianter (Hold, Histogram, Hysteresis, MACD+Stoch og Adaptive Hold). "
               "Foreløpig én ny handelsenhet og fast 5m-struktur; ingen AEn-pyramidering eller Impulse Detector. "
               "AI Manager kan legges på som LIVE-modifikator.")
    # These are display-only presets: canonical saved strategy keys still point
    # to existing deterministic V3 engines. PreCross models are NOT implemented.
    base_keys=tuple(x.key for x in STRATEGIES_V3)
    keys=base_keys+tuple(p.selector_key for p in AI_LIVE_PRESETS_V3)
    initial_choice=initial_selector_key_v3(
        strategy_key=config.strategy_key,timeframe=config.timeframe,
        modifiers=config.modifiers)
    a,b=st.columns(2)
    selected=a.selectbox(
        'Strategi / AI-oppsett (LIVE)',keys,index=keys.index(initial_choice),
        format_func=lambda k: (PRESETS_BY_KEY_V3[k].label
            if k in PRESETS_BY_KEY_V3 else next(x.label for x in STRATEGIES_V3 if x.key==k)
            + ('' if next(x for x in STRATEGIES_V3 if x.key==k).runtime_ready
               else ' · ikke LIVE')),
        key=f'{key_prefix}:strategy:{trader_id}',
    )
    is_ai_preset=ai_preset_selected_v3(selected)
    strategy=PRESETS_BY_KEY_V3[selected].strategy_key if is_ai_preset else selected
    # Suggest the fixed 1m / 15m rhythm context on a *new selection*.
    # This is UI form state only; nothing is saved or armed by a dropdown change.
    viewed_key=f'{key_prefix}:last-viewed-strategy:{trader_id}'
    previously_viewed=st.session_state.get(viewed_key,initial_choice)
    suggested=_rhythm_selection_defaults_v3(previously_viewed,strategy)
    if 'timeframe' in suggested:
        st.session_state[f'{key_prefix}:timeframe:{trader_id}']=suggested['timeframe']
    if 'regime_timeframe' in suggested:
        st.session_state[f'{key_prefix}:regime-timeframe:{trader_id}']=suggested['regime_timeframe']
    st.session_state[viewed_key]=selected
    if is_ai_preset:
        # Preset is a recipe, not an independent new engine. Force the visible
        # time and AI toggle before those widgets are constructed this run.
        chosen=PRESETS_BY_KEY_V3[selected]
        st.session_state[f'{key_prefix}:timeframe:{trader_id}']=chosen.timeframe
        st.session_state[f'{key_prefix}:mod:{trader_id}:ai-loss-manager']=True
        st.info(f"{chosen.label}: bruker eksisterende {strategy} og "
                "AI Loss Manager · LIVE. Ingen ny PreCross-strategi; "
                "lagres først når du trykker «Bruk på denne instansen».")
    # One context-sensitive help control serves every catalog strategy.
    # Keep the actual names and summaries in the canonical registry to avoid
    # TradingDesk vs fleet discrepancies.
    help_spec=next(x for x in STRATEGIES_V3 if x.key==strategy)
    with a.popover("❔", help="Hva gjør den valgte strategien?"):
        st.markdown(f"**{help_spec.label}**")
        st.write(help_spec.description)
        st.caption(
            "Signalperiode velges separat. Nye strategier endrer ingen "
            "eksisterende LIVE-konto før du uttrykkelig lagrer/aktiverer dem."
        )
    timeframe=b.selectbox(
        'Signalperiode (S)', TIMEFRAMES_V3, index=TIMEFRAMES_V3.index(
            PRESETS_BY_KEY_V3[selected].timeframe if is_ai_preset else config.timeframe),
        format_func=lambda value: value if value in LIVE_TIMEFRAMES_V3 else f'{value} · ikke LIVE',
        key=f'{key_prefix}:timeframe:{trader_id}',disabled=is_ai_preset,
    )
    regime_timeframe=config.regime_timeframe
    if strategy in REGIME_STRATEGIES_V3:
        regime_timeframe=st.selectbox(
            'Regimeperiode (R)',
            REGIME_TIMEFRAMES_V3,
            index=REGIME_TIMEFRAMES_V3.index(config.regime_timeframe),
            key=f'{key_prefix}:regime-timeframe:{trader_id}',
            help='MACD på R-perioden bestemmer tillatt side. Histogram på S-perioden bygger/reduserer eksponeringen.',
        )
        selected_label=strategy_display_label_v3(strategy,timeframe,regime_timeframe)
        if selected_label != active_label:
            st.caption(f'Valgt, ikke lagret: {selected_label} · aktiv nå: {active_label}')
        else:
            st.caption(f'Aktiv nå: {active_label}')
    spec=next(x for x in STRATEGIES_V3 if x.key==strategy)
    if not spec.runtime_ready: st.warning('Denne strategien er SIM/sammenlignbar, men ikke runtime-klar for LIVE.')
    p1,p2=st.columns(2); budget=p1.number_input('Budsjett (NOK)',min_value=100.0,value=float(policy.budget_nok if policy else 2000),step=100.0,key=f'{key_prefix}:budget:{trader_id}'); exposure=p2.slider('Eksponering (%)',1,100,int(policy.exposure_pct if policy else 100),key=f'{key_prefix}:exposure:{trader_id}')
    st.caption(f'LIVE kapitalgrense: {float(budget)*float(exposure)/100.0:,.0f} NOK · håndheves mot Saxo precheck (margin/cash).')
    st.markdown('**AI-forvaltning**')
    st.caption("AI Manager er et tillegg til grunnstrategien, ikke en egen "
               "PreCross-strategi. Ved vedvarende tap kan AI foreslå HOLD, "
               "REDUCE eller FLAT. LIVE utfører kun reduksjon/lukking, "
               "aldri en ny AI-styrt inngang.")
    ai_enabled=st.toggle(
        'AI Loss Manager · LIVE (styr eksisterende posisjon)',
        value='ai-loss-manager' in config.modifiers,
        key=f'{key_prefix}:mod:{trader_id}:ai-loss-manager',
        disabled=is_ai_preset,
        help='AI-kontroll og tidsgrense finnes også under handelskartet. '
             'AI-lukking går gjennom vanlig Saxo-ordrekjede.',
    )
    enabled=['ai-loss-manager'] if (ai_enabled or is_ai_preset) else []
    st.markdown('**Andre options / modifiers**')
    other_modifiers=[item for item in MODIFIERS_V3 if item.key!='ai-loss-manager']
    cols=st.columns(3)
    for n,item in enumerate(other_modifiers):
        label=item.label if item.key in LIVE_MODIFIERS_V3 else f'{item.label} · ikke LIVE'
        help_text=item.description + ('' if item.key in LIVE_MODIFIERS_V3 else ' Lagres for V3/SIM, men er ikke koblet til LIVE-runtime ennå.')
        if cols[n%3].toggle(label,value=item.key in config.modifiers,key=f'{key_prefix}:mod:{trader_id}:{item.key}',help=help_text):
            enabled.append(item.key)
    mode=st.selectbox(
        'Kontrollmodus', CONTROL_MODES_V3, index=CONTROL_MODES_V3.index(config.control_mode),
        format_func=lambda value: value if value in LIVE_CONTROL_MODES_V3 else f'{value} · ikke LIVE',
        key=f'{key_prefix}:mode:{trader_id}',
    )
    selected_strategy,selected_timeframe,selected_modifiers=resolve_selector_draft_v3(
        selector_key=selected,timeframe=timeframe,modifiers=tuple(enabled))
    desired=AutoTraderConfigV3(
        trader_id,selected_strategy,selected_timeframe,mode,
        selected_modifiers,regime_timeframe
    ); desired_policy=ExecutionPolicyV3(trader_id,float(budget),float(exposure)); changed=desired!=config or desired_policy!=policy
    desired_label=strategy_display_label_v3(desired.strategy_key,desired.timeframe,desired.regime_timeframe)
    if desired.strategy_key not in REGIME_STRATEGIES_V3 and desired_label!=active_label:
        st.caption(f'Valgt, ikke lagret: {desired_label} · aktiv nå: {active_label}')
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
        if authority.sim_armed:
            st.warning('SIM kan ikke kjøre denne configen: ' + ' · '.join(sim_issues)
                       + '. LIVE påvirkes ikke dersom LIVE-configen er gyldig.')
        else:
            with st.expander('SIM-kompatibilitet (påvirker ikke LIVE)',expanded=False):
                st.caption('SIM støtter ikke dette oppsettet: ' + ' · '.join(sim_issues))
    save_blocked=_instance_save_blocked_v3(
        live_armed=authority.live_armed,sim_armed=authority.sim_armed,
        live_issues=live_issues,sim_issues=sim_issues)
    if save_blocked:
        st.caption('Valgt config støttes ikke av aktiv motor. Slå motoren av eller velg et kompatibelt oppsett.')
    if st.button('Bruk på denne instansen',type='primary',disabled=(not changed or save_blocked),width='stretch',key=f'{key_prefix}:save:{trader_id}'):
        save_autotrader_config_v3(desired); save_execution_policy_v3(desired_policy)
        # A removed safety option cannot retain previously granted approval.
        if 'whipsaw' in config.modifiers and 'whipsaw' not in desired.modifiers:
            set_whipsaw_live_approval_v3(trader_id,False)
        st.session_state[f'{key_prefix}:flash:{trader_id}']=f'Aktiv config lagret: {desired_label}'
        st.rerun()

    if 'whipsaw' in config.modifiers:
        approved=is_whipsaw_live_approved_v3(trader_id)
        if approved:
            st.success("LIVE Whipsaw Detector godkjent på denne instansen.")
            if st.button("Tilbakekall Whipsaw LIVE-godkjenning",
                         key=f'{key_prefix}:whip-revoke:{trader_id}'):
                set_whipsaw_live_approval_v3(trader_id,False)
                st.rerun()
        else:
            st.warning(
                "Whipsaw er valgt i config, men mangler separat LIVE-godkjenning. "
                "Nye innganger og ADD holdes sperret til du godkjenner. "
                "REDUCE og CLOSE tillates fortsatt."
            )
            if st.button("Godkjenn Whipsaw Detector for LIVE på denne instansen",
                         key=f'{key_prefix}:whip-authorize:{trader_id}'):
                set_whipsaw_live_approval_v3(trader_id,True)
                st.rerun()
    if 'volatility-pause' in config.modifiers:
        st.caption(
            "Volatility Pause er aktiv i denne instansens LIVE-config: "
            "blokkerer nye innganger/ADD ved HIGH_VOL. "
            "Utganger og reduksjoner er alltid tillatt."
        )
    flash_key=f'{key_prefix}:flash:{trader_id}'
    if flash_key in st.session_state:
        st.success(st.session_state.pop(flash_key))
    st.markdown('**Instans-recovery**')
    st.caption(
        'Kontroller V3-ordrelås og faktisk Saxo-posisjon uten å slette '
        'ordre-/handelshistorikk. Kun gamle, verifisert usendte RESERVED '
        'kan frigjøres; SUBMITTING, SUBMITTED og UNKNOWN forblir sperret. '
        'Strategi, konto, budsjett og LIVE PÅ/AV beholdes.'
    )
    from autotrader_v3_order_guard_v1 import pending_order as pending_order_v3
    from autotrader_v3_operator_order_recovery_v1 import OrderRecoveryDeniedV3
    from autotrader_v3_instance_reset_v1 import reset_instance_safely_v3
    recovery_pending=pending_order_v3(
        account_id=str(instance.account_id),
        uic=int(instance.uic),asset_type=str(instance.asset_type),
    )
    if recovery_pending:
        pending_state=str(recovery_pending.get('state') or 'UNKNOWN')
        st.warning(
            f'Uavklart ordrelås: {pending_state}. '
            'Reset nekter alle mulige innsendte Saxo-ordrer.'
        )
    if st.button(
        'Kontroller / reset fastlåst instans',
        key=f'{key_prefix}:safe-reset:{trader_id}',width='stretch',
        help='Bare dokumentert usendt RESERVED kan frigjøres. '
             'Ingenting slettes hos Saxo; ingen ordre opprettes.',
    ):
        try:
            outcome=reset_instance_safely_v3(instance_id=trader_id)
        except OrderRecoveryDeniedV3 as exc:
            st.error('Reset sperret: '+str(exc))
        except Exception as exc:
            # Broker errors may include sensitive payloads: show only type.
            st.error('Reset sperret ved Saxo-/databasekontroll: '+type(exc).__name__)
        else:
            st.session_state[f'{key_prefix}:recovery-result:{trader_id}']=outcome.detail
            st.rerun()
    recovery_key=f'{key_prefix}:recovery-result:{trader_id}'
    if recovery_key in st.session_state:
        st.success(st.session_state.pop(recovery_key))
    st.markdown('**Execution authority**')
    if authority.live_armed:
        st.success(f'LIVE PÅ · {account_title} · {active_label} · UIC {instance.uic}')
        st.caption('Slå LIVE av stopper nye AutoTrader-ordrer. Eksisterende Saxo-posisjon beholdes.')
        if st.button('Slå LIVE av · behold posisjon',width='stretch',key=f'{key_prefix}:live-off:{trader_id}'):
            try:set_live_enabled_v3(trader_id,False,account_id=instance.account_id)
            except Exception as exc:st.error(f'Kunne ikke slå LIVE av: {exc}')
            else:
                st.session_state[flash_key]=f'LIVE slått AV for {account_title}. Eksisterende posisjon er beholdt.'
                st.rerun()
    else:
        st.caption(f'LIVE AV · {account_title} · aktiv config {active_label} · eksisterende posisjon endres ikke.')
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
            else:
                st.session_state[flash_key]=f'LIVE slått PÅ for {account_title}.'
                st.rerun()

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
