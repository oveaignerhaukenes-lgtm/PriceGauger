from __future__ import annotations

"""Shared operator controls for one V3 engine instance.

The page is not the owner of strategy/risk state. TradingDesk and the fleet page both
render this component against the same durable instance config and execution policy.
"""

import streamlit as st

from autotrader_v3_config_v1 import AutoTraderConfigV3, load_autotrader_config_v3, save_autotrader_config_v3
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3, load_execution_policy_v3, save_execution_policy_v3
from autotrader_v3_modifier_settings_v1 import load_modifier_settings_v3, save_modifier_settings_v3
from autotrader_v3_registry_v1 import CONTROL_MODES_V3, MODIFIERS_V3, STRATEGIES_V3, TIMEFRAMES_V3


def render_v3_instance_controls_v1(instance, *, key_prefix: str, compact: bool = False) -> None:
    trader_id = str(instance.instance_id)
    config = load_autotrader_config_v3(trader_id)
    policy = load_execution_policy_v3(trader_id)

    st.markdown(f"**{instance.market_name} · {instance.account_id}**")
    st.caption(f"V3 instance {trader_id[:8]} · UIC {instance.uic} · {instance.asset_type}")

    strategy_keys = tuple(item.key for item in STRATEGIES_V3)
    runtime_keys = tuple(item.key for item in STRATEGIES_V3 if item.runtime_ready)
    c1, c2 = st.columns(2)
    strategy_key = c1.selectbox(
        "Strategi",
        strategy_keys,
        index=strategy_keys.index(config.strategy_key),
        format_func=lambda key: next(item.label for item in STRATEGIES_V3 if item.key == key),
        key=f"{key_prefix}:strategy:{trader_id}",
    )
    timeframe = c2.selectbox(
        "Periode",
        TIMEFRAMES_V3,
        index=TIMEFRAMES_V3.index(config.timeframe),
        key=f"{key_prefix}:timeframe:{trader_id}",
    )
    spec = next(item for item in STRATEGIES_V3 if item.key == strategy_key)
    if strategy_key not in runtime_keys:
        st.warning("Strategien er synlig for sammenligning, men er ikke runtime-klar og kan ikke få LIVE-ordreautoritet.")
    elif not compact:
        st.caption(spec.description)

    budget_default = float(policy.budget_nok if policy else 2000.0)
    exposure_default = int(policy.exposure_pct if policy else 100)
    p1, p2 = st.columns(2)
    budget_nok = p1.number_input("Budsjett (NOK)", min_value=100.0, value=budget_default, step=100.0,
                                 key=f"{key_prefix}:budget:{trader_id}")
    exposure_pct = p2.slider("Eksponering (%)", 1, 100, exposure_default,
                             key=f"{key_prefix}:exposure:{trader_id}")

    st.markdown("**Options / modifiers**")
    enabled: list[str] = []
    columns = st.columns(2 if compact else 3)
    for index, modifier in enumerate(MODIFIERS_V3):
        with columns[index % len(columns)]:
            on = st.toggle(modifier.label, value=modifier.key in config.modifiers,
                           key=f"{key_prefix}:mod:{trader_id}:{modifier.key}", help=modifier.description)
            if on:
                enabled.append(modifier.key)
            with st.popover("⚙", disabled=not on):
                settings = load_modifier_settings_v3(trader_id, modifier.key)
                st.caption(modifier.description)
                st.json(settings)
                # Detailed parameter editors remain canonical and may be extended here;
                # both pages deliberately share this one component rather than copying state.

    control_mode = st.selectbox(
        "Kontrollmodus", CONTROL_MODES_V3, index=CONTROL_MODES_V3.index(config.control_mode),
        key=f"{key_prefix}:mode:{trader_id}",
    )
    desired = AutoTraderConfigV3(trader_id=trader_id, strategy_key=strategy_key,
                                 timeframe=timeframe, control_mode=control_mode,
                                 modifiers=tuple(enabled))
    desired_policy = ExecutionPolicyV3(trader_id, float(budget_nok), float(exposure_pct))
    changed = desired != config or desired_policy != policy
    if st.button("Bruk på denne instansen", type="primary" if changed else "secondary",
                 disabled=not changed, width="stretch", key=f"{key_prefix}:save:{trader_id}"):
        save_autotrader_config_v3(desired)
        save_execution_policy_v3(desired_policy)
        st.success("Instansen er oppdatert. TradingDesk og AutoTrader leser nå samme canonical config.")
        st.rerun()


__all__ = ["render_v3_instance_controls_v1"]
