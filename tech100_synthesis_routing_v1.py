"""PAPER-only adapters for strategy context and a dedicated impulse instance.

Do not connect this module directly to Saxo. Any future LIVE route must go
through the existing V3 owner, margin, order-lock and broker reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from tech100_four_channel_synthesis_v1 import IMPULSE, SynthesisResult


@dataclass(frozen=True)
class StrategyContextDecision:
    requested_target_side: int
    allowed_target_side: int
    reason: str


def apply_entry_context(
    *, result: SynthesisResult,
    held_side: int,
    proposed_side: int,
) -> StrategyContextDecision:
    """Gate *entries* only; never block closing or force an extra order.

    The technical strategy owns timing/exits. The synthesis never invents a
    new entry. A disallowed reversal may still reduce existing risk to FLAT.
    """
    if held_side not in (-1, 0, 1) or proposed_side not in (-1, 0, 1):
        raise ValueError("side must be -1, 0 or +1")
    if proposed_side == 0:
        return StrategyContextDecision(proposed_side, 0, "EXIT_ALWAYS_ALLOWED")
    if proposed_side == held_side:
        return StrategyContextDecision(proposed_side, proposed_side, "HOLD_NOT_OVERRIDDEN")
    # Partial input is useful diagnostically, but cannot authorize entries.
    supported = result.status == "PAPER_ONLY"
    expected = "LONG" if proposed_side > 0 else "SHORT"
    if supported and result.direction == expected:
        return StrategyContextDecision(proposed_side, proposed_side, "CONTEXT_SUPPORTS_ENTRY")
    # A change from LONG to SHORT (or vice versa) must not preserve a position
    # simply because the new entry is vetoed; permit closing existing risk.
    return StrategyContextDecision(proposed_side, 0, "ENTRY_BLOCKED_EXIT_STILL_ALLOWED")


@dataclass(frozen=True)
class PaperImpulseIntent:
    instance_key: str
    signal_id: str
    target_side: int
    created_at: datetime
    expires_at: datetime
    max_position_age: timedelta
    reason: str
    live_authorized: bool = False


def impulse_paper_intent(
    *,
    result: SynthesisResult,
    instance_key: str,
    time_to_live: timedelta = timedelta(seconds=30),
    max_position_age: timedelta = timedelta(minutes=5),
) -> PaperImpulseIntent | None:
    """Emit an auditable *paper* target, never an executable Saxo request.

    Only a selected validated impulse signal can open an independent trade.
    No signal means FLAT, not an opposite-side default. Deduplication can use
    the stable signal_id in a future V3 inbox under explicit account ownership.
    """
    if not instance_key.strip() or time_to_live <= timedelta(0) or max_position_age <= timedelta(0):
        raise ValueError("instance, positive TTL and maximum position age required")
    if (IMPULSE not in result.selected or result.status != "PAPER_ONLY"
            or result.direction not in {"LONG", "SHORT"}):
        return None
    side = 1 if result.direction == "LONG" else -1
    # Include the assessment instant: a repeated evaluation of the *same*
    # snapshot yields the same ID; a later snapshot is a distinct proposal.
    stamp = result.at.astimezone(timezone.utc)
    digest = sha256(f"{instance_key}|{stamp.isoformat()}|{result.selected}|{side}".encode()).hexdigest()[:24]
    return PaperImpulseIntent(
        instance_key=instance_key,
        signal_id=f"tech100-synthesis-v1:{digest}",
        target_side=side,
        created_at=stamp,
        expires_at=stamp + time_to_live,
        max_position_age=max_position_age,
        reason="Validated research impulse; requires independent V3 account and execution approval",
    )
