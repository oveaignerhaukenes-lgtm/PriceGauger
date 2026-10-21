"""Low-cost, bounded and broker-free evidence for V3 LIVE signal timing.

Only record an actionable base target (including a safety-vetoed target);
the executor remains the sole owner of Saxo orders and reconciliation.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from math import isfinite

_MAX_KEYS = 256
_SEEN = OrderedDict()


def _short(value, limit=160):
    return " ".join(str(value or "").split())[:limit]


def v3_transition_trace(*, trader_id, strategy_key, timeframe, now,
                        actual_amount, decision, approved_amount):
    """Return one log record per minute/transition, else None.

    Pure diagnostic: no DB, broker, account ID or personal data. An invalid
    decision never blocks the Saxo execution pipeline.
    """
    try:
        at = now if isinstance(now, datetime) else datetime.fromisoformat(str(now).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        minute = at.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
        actual, target, approved = (
            float(actual_amount), float(decision.decision.target.amount), float(approved_amount)
        )
        if not all(isfinite(v) for v in (actual, target, approved)):
            return None
        if abs(target-actual) <= 1e-10:
            return None
        action = _short(decision.decision.action, 50)
        reason = _short(decision.decision.reason)
        key = _short(decision.decision_key, 160)
        identity=(str(trader_id), str(strategy_key), minute, round(actual,8),
                  round(target,8),round(approved,8), action)
        if identity in _SEEN:
            return None
        _SEEN[identity]=None
        if len(_SEEN)>_MAX_KEYS:
            _SEEN.popitem(last=False)
        return ("v3 LIVE SIGNAL_TRACE trader=%s strategy=%s tf=%s minute=%s "
                "decision=%s action=%s actual=%g raw_target=%g approved=%g "
                "veto=%s reason=%s") % (
                    _short(trader_id,64),_short(strategy_key,70),_short(timeframe,14),
                    minute,key,action,actual,target,approved,
                    "yes" if abs(approved-target)>1e-10 else "no",reason)
    except (ValueError, TypeError, OverflowError, AttributeError):
        return None
