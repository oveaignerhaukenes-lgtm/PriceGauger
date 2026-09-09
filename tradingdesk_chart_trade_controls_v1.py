from __future__ import annotations

import streamlit as st

from autotrader_manual_target_v2 import load_manual_target_quote_v2, request_manual_target_v2
from autotrader_risk_control_v2 import _position_observations_v2
from saxo_provider import LIVE_BASE_URL, configured_client
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanager_simple_v1 import (
    _account_info,
    _active_live_for_context_v1,
    _direction_v1,
    _ensure_execution_ready_v1,
    _exact_observation_v1,
)


_CHART_TRADE_CONTROLS_JS = r"""
export default function(component) {
    const { data, parentElement, setTriggerValue } = component;
    parentElement.style.height = '0px';
    parentElement.style.minHeight = '0px';
    parentElement.style.overflow = 'visible';

    const chartId = String(data.chart_id || '');
    const registry = window.__pricegaugerLightweightCharts;
    const entry = registry?.get?.(chartId);
    if (!entry?.root) return;

    const root = entry.root;
    const controlId = `pg-chart-trade-controls:${chartId}`;
    let controls = root.querySelector(`[data-pg-chart-trade-controls="${CSS.escape(controlId)}"]`);
    if (!controls) {
        controls = document.createElement('div');
        controls.dataset.pgChartTradeControls = controlId;
        Object.assign(controls.style, {
            position: 'absolute',
            left: '8px',
            top: '8px',
            zIndex: '14',
            display: 'flex',
            gap: '6px',
            alignItems: 'center',
            pointerEvents: 'auto',
            font: '700 11px/1 system-ui,-apple-system,sans-serif',
        });
        root.appendChild(controls);
    }

    function button(kind, label, disabled) {
        let node = controls.querySelector(`[data-action="${kind}"]`);
        if (!node) {
            node = document.createElement('button');
            node.type = 'button';
            node.dataset.action = kind;
            Object.assign(node.style, {
                border: '1px solid rgba(255,255,255,.24)',
                borderRadius: '6px',
                padding: '6px 8px',
                minWidth: '72px',
                color: '#ffffff',
                boxShadow: '0 1px 4px rgba(0,0,0,.28)',
                cursor: 'pointer',
                font: 'inherit',
                backdropFilter: 'blur(3px)',
                WebkitBackdropFilter: 'blur(3px)',
            });
            node.onclick = (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (node.disabled) return;
                node.disabled = true;
                setTriggerValue('trade_action', kind === 'BUY' ? 'LONG' : 'SHORT');
            };
            controls.appendChild(node);
        }
        node.textContent = label;
        node.disabled = Boolean(disabled);
        node.style.background = kind === 'BUY' ? 'rgba(220,38,38,.92)' : 'rgba(37,99,235,.92)';
        node.style.opacity = node.disabled ? '.45' : '1';
        node.style.cursor = node.disabled ? 'default' : 'pointer';
    }

    button('BUY', String(data.buy_label || 'BUY'), Boolean(data.buy_disabled));
    button('SELL', String(data.sell_label || 'SELL'), Boolean(data.sell_disabled));
}
"""


_chart_trade_controls_component = st.components.v2.component(
    "pricegauger_tradingdesk_chart_trade_controls_v1",
    js=_CHART_TRADE_CONTROLS_JS,
    isolate_styles=False,
)


def _format_quote_label_v1(side: str, value: float | None) -> str:
    if value is None:
        return side
    return f"{side} {value:,.2f}".replace(",", " ")


def render_tradingdesk_chart_trade_controls_v1(
    context: TradingDeskV2Context,
    *,
    observations: tuple | None = None,
) -> None:
    """Mount chart BUY/SELL shortcuts onto the canonical Lightweight chart.

    The browser buttons only emit LONG/SHORT trigger values. Python routes those
    triggers through `request_manual_target_v2`, so chart controls share the exact
    durable execution-request lifecycle used by the AutoManager BUY/SELL controls.
    They never POST to Saxo from browser code.
    """
    client = configured_client()
    if client is None or client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        return

    try:
        enrollment = _active_live_for_context_v1(context)
        if enrollment is None:
            return
        current_observations = tuple(observations) if observations is not None else _position_observations_v2(client)
        observation = _exact_observation_v1(enrollment, current_observations)
        observed_direction = _direction_v1(observation)
        account_key, _ = _account_info(client, enrollment.account_id)
        quote = load_manual_target_quote_v2(enrollment, account_key=account_key)
        quote_error = None
    except Exception as exc:
        quote = None
        quote_error = str(exc)
        observed_direction = "UNKNOWN"

    component_key = f"td-chart-trade-controls:{context.market_id}:{context.instrument_id}"
    result = _chart_trade_controls_component(
        key=component_key,
        data={
            "chart_id": f"TradingDeskLightweight:{context.market_name}",
            "buy_label": _format_quote_label_v1("BUY", None if quote is None else quote.ask),
            "sell_label": _format_quote_label_v1("SELL", None if quote is None else quote.bid),
            "buy_disabled": quote is None or observed_direction == "LONG",
            "sell_disabled": quote is None or observed_direction == "SHORT",
        },
        height=0,
        on_trade_action_change=lambda: None,
    )

    action = getattr(result, "trade_action", None)
    if action not in {"LONG", "SHORT"}:
        if quote_error:
            st.caption(f"Chart BUY/SELL venter på Saxo-pris: {quote_error}")
        return

    try:
        enrollment = _ensure_execution_ready_v1(enrollment)
        request_manual_target_v2(enrollment, target_direction=str(action))
    except Exception as exc:
        st.error(f"Chart {action}-mål kunne ikke settes: {exc}")
    else:
        st.toast(f"Chart-mål satt: {action}")
        st.rerun(scope="fragment")


__all__ = ["render_tradingdesk_chart_trade_controls_v1"]
