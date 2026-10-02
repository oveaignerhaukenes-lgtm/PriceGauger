"""Classify durable V3 pending orders without ever authorizing a retry."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class PendingResolutionV3:
    state: str
    age_seconds: float | None
    detail: str


def _parse_timestamp(value: object) -> datetime | None:
    text=str(value or '').strip()
    if not text:
        return None
    try:
        parsed=datetime.fromisoformat(text.replace('Z','+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_pending_resolution_v3(*, reconciliation_state: str, updated_at: object,
                                   now: datetime | None = None,
                                   stale_after_seconds: float = 120.0) -> PendingResolutionV3:
    """Expose WAIT that has outlived broker propagation as AMBIGUOUS.

    This function is deliberately diagnostic-only. AMBIGUOUS retains the durable
    order lock; it never marks an order failed and never permits automatic retry.
    """
    state=str(reconciliation_state or '').strip().upper()
    stamp=_parse_timestamp(updated_at)
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age=None if stamp is None else max(0.0,(current-stamp).total_seconds())
    if state == 'CONFIRMED':
        return PendingResolutionV3('RECONCILED',age,'broker inventory reached expected post-order state')
    if state == 'CONFLICT':
        return PendingResolutionV3('AMBIGUOUS',age,'inventory conflicts with both pre-order and expected state; keep lock')
    if state != 'WAIT':
        return PendingResolutionV3('AMBIGUOUS',age,'unknown reconciliation state; keep lock')
    if age is None:
        return PendingResolutionV3('AMBIGUOUS',None,'pending timestamp unavailable; keep lock')
    if age >= max(0.0,float(stale_after_seconds)):
        return PendingResolutionV3('AMBIGUOUS',age,'pre-order inventory persisted beyond propagation window; broker evidence required before retry')
    return PendingResolutionV3('WAITING',age,'pre-order inventory unchanged inside propagation window')


__all__=['PendingResolutionV3','classify_pending_resolution_v3']
