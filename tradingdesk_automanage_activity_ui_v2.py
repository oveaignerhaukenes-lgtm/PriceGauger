from __future__ import annotations

"""Read-only AutoManage activity timeline renderer."""

import streamlit as st

from autotrader_activity_log_v2 import load_automanager_activity_log_v2
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from time_display_v2 import oslo_label


def render_automanager_activity_log_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> None:
    observed_direction_override = None
    exact_close_authority_override = None
    if observations is not None:
        observation = next(
            (
                item
                for item in observations
                if item.account_id == enrollment.account_id
                and int(item.uic) == int(enrollment.uic)
                and item.asset_type == enrollment.asset_type
            ),
            None,
        )
        if observation is None:
            observed_direction_override = "FLAT"
        else:
            observed_direction_override = (
                "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
            )
            exact_close_authority_override = is_position_managed_v1(observation)
    try:
        activity = load_automanager_activity_log_v2(
            enrollment,
            limit=8,
            observed_direction_override=observed_direction_override,
            exact_close_authority_override=exact_close_authority_override,
        )
    except Exception as exc:
        st.caption(f"Hendelsesloggen venter: {exc}")
        return

    st.markdown("**Hendelser og neste status**")
    st.info(f"**Status nå: {activity.lifecycle_status}**\n\nNeste: {activity.next_step}")
    with st.expander(f"Siste hendelser ({len(activity.events)})", expanded=True):
        for event in activity.events:
            with st.container(border=True):
                st.caption(f"{oslo_label(event.occurred_at)} · {event.engine}")
                st.markdown(f"**{event.title}**")
                details = [event.detail, event.status]
                if event.realized_net_pnl is not None:
                    currency = event.currency or ""
                    details.append(f"Realisert netto {event.realized_net_pnl:+.2f} {currency}".strip())
                st.caption(" · ".join(item for item in details if item))


__all__ = ["render_automanager_activity_log_v2"]
