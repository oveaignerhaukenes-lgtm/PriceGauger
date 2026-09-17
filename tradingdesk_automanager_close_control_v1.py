from __future__ import annotations

import streamlit as st

from autotrader_manage_control_v1 import set_auto_manage_enabled_v1
from autotrader_manual_close_v1 import request_manual_close_v1
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_automanager_simple_v1 import (
    _active_live_for_context_v1,
    _ensure_execution_ready_v1,
    _exact_observation_v1,
)


def render_close_position_control_v1(
    context: TradingDeskV2Context,
    *,
    observations: tuple | None,
) -> None:
    """Render an explicit user FLAT control without browser-to-Saxo authority."""
    if observations is None:
        return
    try:
        enrollment = _active_live_for_context_v1(context)
    except Exception as exc:
        st.caption(f"Close position venter: {exc}")
        return
    if enrollment is None:
        return
    try:
        observation = _exact_observation_v1(enrollment, tuple(observations))
    except Exception as exc:
        st.caption(f"Close position venter: {exc}")
        return

    clicked = st.button(
        "Close position",
        key=f"td-simple-close:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}",
        disabled=observation is None,
        width="stretch",
        help=(
            "Setter mål FLAT gjennom PriceGaugers vanlige CLOSE-livssyklus. "
            "AutoTrade pauses samtidig slik at strategien ikke åpner posisjonen igjen straks etterpå."
        ),
    )
    if not clicked:
        return

    autotrade_key = (
        f"td-simple-autotrade:{enrollment.account_id}:{enrollment.uic}:{enrollment.asset_type}"
    )
    try:
        enrollment = _ensure_execution_ready_v1(enrollment)
        # Operator CLOSE takes precedence over strategy authority. Pause first, so
        # even a later request/precheck failure cannot leave a strategy free to race
        # the user's explicit flatten command.
        set_auto_manage_enabled_v1(enrollment, False)
        st.session_state[autotrade_key] = False
        result = request_manual_close_v1(enrollment, observation=observation)
    except Exception as exc:
        st.error(f"Close position feilet. AutoTrade er pauset: {exc}")
        return

    if result.already_flat:
        st.success("Saxo er allerede FLAT. AutoTrade er pauset.")
    elif result.request_created:
        st.success("Close position sendt til execution-motoren. AutoTrade er pauset.")
    else:
        st.success("Close position er registrert og execution fortsetter. AutoTrade er pauset.")
    st.rerun()


__all__ = ["render_close_position_control_v1"]
