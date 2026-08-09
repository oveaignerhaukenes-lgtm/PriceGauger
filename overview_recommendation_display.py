from __future__ import annotations


_DIRECTION_ACTIONS = {
    "LONG_BIAS": "LONG",
    "SHORT_BIAS": "SHORT",
    "NEUTRAL": "HOLD",
}


def recommendation_action(direction: str) -> str:
    """Expose the model direction for observation even when it is provisional.

    This is presentation only. ACTIONABLE/PROVISIONAL remains a separate status
    and this function does not relax any execution, precheck, or trading guardrail.
    Unknown, conflicted, insufficient-data, and stale directions remain NO-TRADE.
    """

    return _DIRECTION_ACTIONS.get(str(direction), "NO-TRADE")
