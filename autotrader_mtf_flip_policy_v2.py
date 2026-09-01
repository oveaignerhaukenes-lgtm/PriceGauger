from __future__ import annotations

from dataclasses import dataclass

from autotrader_mtf_entry_shadow_v2 import (
    CONTEXT_BULLISH,
    CONTEXT_RECOVERING,
    ENTRY_TIMEFRAME_MINUTES,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
)
from autotrader_mtf_short_policy_v2 import CONTEXT_BEARISH, CONTEXT_DETERIORATING


STATE_FLAT = "FLAT"
STATE_PROVISIONAL_LONG = "PROVISIONAL_LONG"
STATE_VALIDATED_10M_LONG = "VALIDATED_10M_LONG"
STATE_CONFIRMED_30M_LONG = "CONFIRMED_30M_LONG"
STATE_PROVISIONAL_SHORT = "PROVISIONAL_SHORT"
STATE_VALIDATED_10M_SHORT = "VALIDATED_10M_SHORT"
STATE_CONFIRMED_30M_SHORT = "CONFIRMED_30M_SHORT"

LONG_STATES = {
    STATE_PROVISIONAL_LONG,
    STATE_VALIDATED_10M_LONG,
    STATE_CONFIRMED_30M_LONG,
}
SHORT_STATES = {
    STATE_PROVISIONAL_SHORT,
    STATE_VALIDATED_10M_SHORT,
    STATE_CONFIRMED_30M_SHORT,
}

ACTION_OPEN_LONG = "OPEN_LONG"
ACTION_OPEN_SHORT = "OPEN_SHORT"
ACTION_CLOSE_FLAT = "CLOSE_FLAT"
ACTION_FLIP_LONG = "FLIP_LONG"
ACTION_FLIP_SHORT = "FLIP_SHORT"
ACTION_CONFIRMATION = "CONFIRMATION"

EVENT_ENTRY_5M_LONG = "ENTRY_5M_LONG"
EVENT_ENTRY_5M_SHORT = "ENTRY_5M_SHORT"
EVENT_REJECT_5M_LONG = "REJECT_5M_LONG"
EVENT_REJECT_5M_SHORT = "REJECT_5M_SHORT"
EVENT_CONFIRM_10M_LONG = "CONFIRM_10M_LONG"
EVENT_CONFIRM_10M_SHORT = "CONFIRM_10M_SHORT"
EVENT_REJECT_10M_LONG = "REJECT_10M_LONG"
EVENT_REJECT_10M_SHORT = "REJECT_10M_SHORT"
EVENT_CONFIRM_30M_LONG = "CONFIRM_30M_LONG"
EVENT_CONFIRM_30M_SHORT = "CONFIRM_30M_SHORT"
EVENT_FLIP_30M_TO_LONG = "FLIP_30M_TO_LONG"
EVENT_FLIP_30M_TO_SHORT = "FLIP_30M_TO_SHORT"

DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
DIRECTION_FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class MtfFlipDecisionV2:
    event_type: str
    action: str
    desired_state: str
    desired_direction: str | None
    carry_reversal: bool
    reason: str


def cross_v2(previous: MtfObservationV2, current: MtfObservationV2) -> str | None:
    if previous.spread <= 0.0 < current.spread:
        return "CROSS_UP"
    if previous.spread >= 0.0 > current.spread:
        return "CROSS_DOWN"
    return None


def mtf_flip_decision_v2(
    *,
    state: str,
    timeframe_minutes: int,
    previous: MtfObservationV2,
    current: MtfObservationV2,
    long_context_30m: str,
    short_context_30m: str,
) -> MtfFlipDecisionV2 | None:
    """Pure symmetric 30/10/5 LONG/SHORT policy.

    Early 5m/10m failures flatten only. A fully closed opposite 30m cross is the
    sole event allowed to carry a direction target across CLOSE -> FLAT -> OPEN.
    This prevents fast-clock noise from becoming a one-step reversal contract.
    """
    timeframe = int(timeframe_minutes)
    crossing = cross_v2(previous, current)

    if timeframe == ENTRY_TIMEFRAME_MINUTES:
        if (
            state == STATE_FLAT
            and crossing == "CROSS_UP"
            and long_context_30m in {CONTEXT_BULLISH, CONTEXT_RECOVERING}
        ):
            return MtfFlipDecisionV2(
                EVENT_ENTRY_5M_LONG,
                ACTION_OPEN_LONG,
                STATE_PROVISIONAL_LONG,
                DIRECTION_LONG,
                False,
                f"closed 5m CROSS_UP inside 30m {long_context_30m.lower()} context",
            )
        if (
            state == STATE_FLAT
            and crossing == "CROSS_DOWN"
            and short_context_30m in {CONTEXT_BEARISH, CONTEXT_DETERIORATING}
        ):
            return MtfFlipDecisionV2(
                EVENT_ENTRY_5M_SHORT,
                ACTION_OPEN_SHORT,
                STATE_PROVISIONAL_SHORT,
                DIRECTION_SHORT,
                False,
                f"closed 5m CROSS_DOWN inside 30m {short_context_30m.lower()} context",
            )
        if state == STATE_PROVISIONAL_LONG and crossing == "CROSS_DOWN":
            return MtfFlipDecisionV2(
                EVENT_REJECT_5M_LONG,
                ACTION_CLOSE_FLAT,
                STATE_FLAT,
                DIRECTION_FLAT,
                False,
                "5m long trigger failed before 10m validation; flatten and re-arm",
            )
        if state == STATE_PROVISIONAL_SHORT and crossing == "CROSS_UP":
            return MtfFlipDecisionV2(
                EVENT_REJECT_5M_SHORT,
                ACTION_CLOSE_FLAT,
                STATE_FLAT,
                DIRECTION_FLAT,
                False,
                "5m short trigger failed before 10m validation; flatten and re-arm",
            )
        return None

    if timeframe == VALIDATION_TIMEFRAME_MINUTES:
        if state == STATE_PROVISIONAL_LONG and current.spread > 0.0:
            return MtfFlipDecisionV2(
                EVENT_CONFIRM_10M_LONG,
                ACTION_CONFIRMATION,
                STATE_VALIDATED_10M_LONG,
                None,
                False,
                "closed 10m MACD validates the provisional long entry",
            )
        if state == STATE_PROVISIONAL_SHORT and current.spread < 0.0:
            return MtfFlipDecisionV2(
                EVENT_CONFIRM_10M_SHORT,
                ACTION_CONFIRMATION,
                STATE_VALIDATED_10M_SHORT,
                None,
                False,
                "closed 10m MACD validates the provisional short entry",
            )
        if state == STATE_VALIDATED_10M_LONG and crossing == "CROSS_DOWN":
            return MtfFlipDecisionV2(
                EVENT_REJECT_10M_LONG,
                ACTION_CLOSE_FLAT,
                STATE_FLAT,
                DIRECTION_FLAT,
                False,
                "10m long validation reversed before 30m confirmation; flatten and re-arm",
            )
        if state == STATE_VALIDATED_10M_SHORT and crossing == "CROSS_UP":
            return MtfFlipDecisionV2(
                EVENT_REJECT_10M_SHORT,
                ACTION_CLOSE_FLAT,
                STATE_FLAT,
                DIRECTION_FLAT,
                False,
                "10m short validation reversed before 30m confirmation; flatten and re-arm",
            )
        return None

    if timeframe == REGIME_TIMEFRAME_MINUTES:
        if state in LONG_STATES and crossing == "CROSS_DOWN":
            return MtfFlipDecisionV2(
                EVENT_FLIP_30M_TO_SHORT,
                ACTION_FLIP_SHORT,
                STATE_FLAT,
                DIRECTION_SHORT,
                True,
                "closed 30m CROSS_DOWN reverses the confirmed MTF regime toward SHORT",
            )
        if state in SHORT_STATES and crossing == "CROSS_UP":
            return MtfFlipDecisionV2(
                EVENT_FLIP_30M_TO_LONG,
                ACTION_FLIP_LONG,
                STATE_FLAT,
                DIRECTION_LONG,
                True,
                "closed 30m CROSS_UP reverses the confirmed MTF regime toward LONG",
            )
        if state in {STATE_PROVISIONAL_LONG, STATE_VALIDATED_10M_LONG} and crossing == "CROSS_UP":
            return MtfFlipDecisionV2(
                EVENT_CONFIRM_30M_LONG,
                ACTION_CONFIRMATION,
                STATE_CONFIRMED_30M_LONG,
                None,
                False,
                "closed 30m CROSS_UP confirms the long regime",
            )
        if state in {STATE_PROVISIONAL_SHORT, STATE_VALIDATED_10M_SHORT} and crossing == "CROSS_DOWN":
            return MtfFlipDecisionV2(
                EVENT_CONFIRM_30M_SHORT,
                ACTION_CONFIRMATION,
                STATE_CONFIRMED_30M_SHORT,
                None,
                False,
                "closed 30m CROSS_DOWN confirms the short regime",
            )
        return None

    raise ValueError(f"unsupported MTF timeframe: {timeframe}")


__all__ = [
    "ACTION_CLOSE_FLAT",
    "ACTION_CONFIRMATION",
    "ACTION_FLIP_LONG",
    "ACTION_FLIP_SHORT",
    "ACTION_OPEN_LONG",
    "ACTION_OPEN_SHORT",
    "DIRECTION_FLAT",
    "DIRECTION_LONG",
    "DIRECTION_SHORT",
    "EVENT_CONFIRM_10M_LONG",
    "EVENT_CONFIRM_10M_SHORT",
    "EVENT_CONFIRM_30M_LONG",
    "EVENT_CONFIRM_30M_SHORT",
    "EVENT_ENTRY_5M_LONG",
    "EVENT_ENTRY_5M_SHORT",
    "EVENT_FLIP_30M_TO_LONG",
    "EVENT_FLIP_30M_TO_SHORT",
    "EVENT_REJECT_10M_LONG",
    "EVENT_REJECT_10M_SHORT",
    "EVENT_REJECT_5M_LONG",
    "EVENT_REJECT_5M_SHORT",
    "LONG_STATES",
    "MtfFlipDecisionV2",
    "SHORT_STATES",
    "STATE_CONFIRMED_30M_LONG",
    "STATE_CONFIRMED_30M_SHORT",
    "STATE_FLAT",
    "STATE_PROVISIONAL_LONG",
    "STATE_PROVISIONAL_SHORT",
    "STATE_VALIDATED_10M_LONG",
    "STATE_VALIDATED_10M_SHORT",
    "cross_v2",
    "mtf_flip_decision_v2",
]
