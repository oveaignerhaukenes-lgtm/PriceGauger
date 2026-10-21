"""Bounded, broker-free HyperChase LIVE diagnostic counts.

The 10-second strategy is intentionally strict about real 1s BBO samples.
Summarize why an ARMED/managed instance remains FLAT, once per UTC minute,
without adding DB reads, Saxo calls, or a new order authority.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import datetime, timezone
from math import isfinite

_MAX_INSTANCES = 64
_MAX_ACTION_TYPES = 32
_RECORDS = OrderedDict()


def _minute(value):
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(second=0, microsecond=0)


def count_hyper_decision(*, trader_id, strategy_key, now, action,
                         actual_amount, raw_target, approved_target):
    """Return previous-minute summary on rollover, else None.

    This must be observational: callers must treat errors as diagnostic-only.
    In-memory counters reset at worker restart; they are not trade statistics.
    """
    minute = _minute(now)
    actual, raw, approved = map(float, (actual_amount, raw_target, approved_target))
    if not all(isfinite(x) for x in (actual, raw, approved)):
        return None
    name = str(action).strip().upper()
    # Action is internal V3 enum-like text, never user-supplied prose.
    if not name or len(name)>64 or not all(c.isalnum() or c=="_" for c in name):
        name = "OTHER"
    ident = (str(trader_id), str(strategy_key))
    prior = _RECORDS.get(ident)
    output = None
    if prior is None or prior["minute"] != minute:
        if prior is not None and prior["counts"]:
            counts = ",".join(
                "%s:%s" % (k,prior["counts"][k])
                for k in sorted(prior["counts"])
            )
            output = (
                "hyper chase LIVE GATE_SUMMARY trader=%s strategy=%s "
                "minute=%s evaluations=%d reasons=%s"
            ) % (str(trader_id),str(strategy_key),
                 prior["minute"].isoformat(),prior["evaluations"],counts)
        _RECORDS[ident] = {"minute": minute, "counts": Counter(), "evaluations":0}
        _RECORDS.move_to_end(ident)
        if len(_RECORDS)>_MAX_INSTANCES:
            _RECORDS.popitem(last=False)
    else:
        _RECORDS.move_to_end(ident)
    _RECORDS[ident]["evaluations"]+=1
    c = _RECORDS[ident]["counts"]
    if len(c) >= _MAX_ACTION_TYPES and name not in c:
        name = "OTHER"
    c[name]+=1
    if abs(raw-approved)>1e-10:
        c["RISK_VETO"]+=1
    return output
