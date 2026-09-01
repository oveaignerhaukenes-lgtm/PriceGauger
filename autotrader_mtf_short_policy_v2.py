from __future__ import annotations

from autotrader_mtf_entry_shadow_v2 import (
    ACTION_CONFIRMATION,
    ACTION_WOULD_EXIT,
    ACTION_WOULD_EXIT_REARM,
    ENTRY_TIMEFRAME_MINUTES,
    MtfDecisionV2,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
)


STATE_FLAT = "FLAT"
STATE_PROVISIONAL_SHORT = "PROVISIONAL_SHORT"
STATE_VALIDATED_10M_SHORT = "VALIDATED_10M_SHORT"
STATE_CONFIRMED_30M_SHORT = "CONFIRMED_30M_SHORT"
SHORT_STATES = {
    STATE_PROVISIONAL_SHORT,
    STATE_VALIDATED_10M_SHORT,
    STATE_CONFIRMED_30M_SHORT,
}

CONTEXT_BEARISH = "BEARISH"
CONTEXT_DETERIORATING = "DETERIORATING"
CONTEXT_BULLISH = "BULLISH"
CONTEXT_UNKNOWN = "UNKNOWN"
ALLOWED_ENTRY_CONTEXTS = {CONTEXT_BEARISH, CONTEXT_DETERIORATING}

EVENT_ENTRY_5M_SHORT = "ENTRY_5M_SHORT"
EVENT_REJECT_5M_SHORT = "REJECT_5M_SHORT"
EVENT_CONFIRM_10M_SHORT = "CONFIRM_10M_SHORT"
EVENT_REJECT_10M_SHORT = "REJECT_10M_SHORT"
EVENT_CONFIRM_30M_SHORT = "CONFIRM_30M_SHORT"
EVENT_EXIT_30M_SHORT = "EXIT_30M_SHORT"

ACTION_WOULD_SELL = "WOULD_SELL"


def cross_v2(previous: MtfObservationV2, current: MtfObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return "CROSS_UP"
    if previous.spread >= 0.0 > current.spread:
        return "CROSS_DOWN"
    return None


def short_regime_context_30m_v2(
    previous: MtfObservationV2 | None,
    current: MtfObservationV2 | None,
) -> str:
    """Mirror long-context semantics for early bearish entries.

    DETERIORATING means 30m is still above its signal but the positive spread is
    shrinking. It deliberately allows 5m to attempt SHORT before a full 30m
    CROSS_DOWN, matching the long-side RECOVERING rule in the opposite direction.
    """
    if previous is None or current is None:
        return CONTEXT_UNKNOWN
    if current.spread < 0.0:
        return CONTEXT_BEARISH
    if current.spread < previous.spread:
        return CONTEXT_DETERIORATING
    return CONTEXT_BULLISH


def short_decision_for_observation_v2(
    *,
    state: str,
    timeframe_minutes: int,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    context_30m: str,
) -> MtfDecisionV2 | None:
    """Pure closed-bar MTF SHORT/FLAT policy; no execution authority."""
    crossing = cross_v2(previous, current)
    timeframe = int(timeframe_minutes)

    if timeframe == ENTRY_TIMEFRAME_MINUTES:
        if state == STATE_FLAT and crossing == "CROSS_DOWN" and context_30m in ALLOWED_ENTRY_CONTEXTS:
            return MtfDecisionV2(
                event_type=EVENT_ENTRY_5M_SHORT,
                action=ACTION_WOULD_SELL,
                desired_state=STATE_PROVISIONAL_SHORT,
                reason=f"closed 5m CROSS_DOWN inside 30m {context_30m.lower()} context",
            )
        if state == STATE_PROVISIONAL_SHORT and crossing == "CROSS_UP":
            return MtfDecisionV2(
                event_type=EVENT_REJECT_5M_SHORT,
                action=ACTION_WOULD_EXIT_REARM,
                desired_state=STATE_FLAT,
                reason="5m short trigger failed before 10m validation; exit small and re-arm",
            )
        return None

    if timeframe == VALIDATION_TIMEFRAME_MINUTES:
        if state == STATE_PROVISIONAL_SHORT and current.spread < 0.0:
            return MtfDecisionV2(
                event_type=EVENT_CONFIRM_10M_SHORT,
                action=ACTION_CONFIRMATION,
                desired_state=STATE_VALIDATED_10M_SHORT,
                reason="closed 10m MACD is bearish after provisional 5m short entry",
            )
        if state == STATE_VALIDATED_10M_SHORT and crossing == "CROSS_UP":
            return MtfDecisionV2(
                event_type=EVENT_REJECT_10M_SHORT,
                action=ACTION_WOULD_EXIT_REARM,
                desired_state=STATE_FLAT,
                reason="10m short validation reversed before 30m regime confirmation; exit and re-arm",
            )
        return None

    if timeframe == REGIME_TIMEFRAME_MINUTES:
        if state in SHORT_STATES and crossing == "CROSS_UP":
            return MtfDecisionV2(
                event_type=EVENT_EXIT_30M_SHORT,
                action=ACTION_WOULD_EXIT,
                desired_state=STATE_FLAT,
                reason="closed 30m bullish cross ends the short regime",
            )
        if state in {STATE_PROVISIONAL_SHORT, STATE_VALIDATED_10M_SHORT} and crossing == "CROSS_DOWN":
            return MtfDecisionV2(
                event_type=EVENT_CONFIRM_30M_SHORT,
                action=ACTION_CONFIRMATION,
                desired_state=STATE_CONFIRMED_30M_SHORT,
                reason="closed 30m CROSS_DOWN confirms the short regime",
            )
        return None

    raise ValueError(f"unsupported MTF timeframe: {timeframe}")


__all__ = [
    "ACTION_WOULD_SELL",
    "ALLOWED_ENTRY_CONTEXTS",
    "CONTEXT_BEARISH",
    "CONTEXT_BULLISH",
    "CONTEXT_DETERIORATING",
    "CONTEXT_UNKNOWN",
    "EVENT_CONFIRM_10M_SHORT",
    "EVENT_CONFIRM_30M_SHORT",
    "EVENT_ENTRY_5M_SHORT",
    "EVENT_EXIT_30M_SHORT",
    "EVENT_REJECT_10M_SHORT",
    "EVENT_REJECT_5M_SHORT",
    "SHORT_STATES",
    "STATE_CONFIRMED_30M_SHORT",
    "STATE_FLAT",
    "STATE_PROVISIONAL_SHORT",
    "STATE_VALIDATED_10M_SHORT",
    "cross_v2",
    "short_decision_for_observation_v2",
    "short_regime_context_30m_v2",
]
