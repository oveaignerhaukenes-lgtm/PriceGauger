"""Safe, single-instance V3 reset: reconcile broker truth, never clear a live order.

The only state mutation is a CAS retire of an old, provably unsubmitted
RESERVED intent through the established operator recovery path. SUBMITTING,
SUBMITTED, UNKNOWN and broker-working orders are never silently discarded.
An already clean instance needs no reset: the worker resumes its existing
strategy/config on the next eligible closed bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_order_guard_v1 import pending_order as pending_order_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
from autotrader_v3_operator_order_recovery_v1 import (
    OrderRecoveryDeniedV3,
    _assert_no_working_orders_v3,
    recover_stale_reserved_v3,
)


@dataclass(frozen=True, slots=True)
class InstanceResetResultV3:
    status: str
    detail: str


def reset_instance_safely_v3(
    *, instance_id: str, db_path: str = "pricegauger.db",
    broker=None, now=None,
) -> InstanceResetResultV3:
    """Check one exact account/product boundary and recover only safe RESERVED.

    No broker POST, no position cancellation/closing, no config changes,
    no authority ON/OFF toggle, no signal cursor reset, and no audit deletion.
    This is operator-invoked only; it must never run automatically.
    """
    matches = tuple(x for x in load_v3_instances_v1(db_path=db_path)
                    if x.instance_id == str(instance_id))
    if len(matches) != 1:
        raise OrderRecoveryDeniedV3("V3-instansen mangler eller er ikke entydig.")
    e = matches[0]
    pending = pending_order_v3(
        account_id=e.account_id, uic=e.uic, asset_type=e.asset_type,
        db_path=db_path,
    )
    if pending is not None:
        # No UNKNOWN/SUBMITTING/SUBMITTED retry. Another order could still
        # execute; clearing it creates a double-order risk.
        if pending.get("state") != "RESERVED" or pending.get("broker_order_id"):
            raise OrderRecoveryDeniedV3(
                "Uavklart Saxo-ordre kan ikke resettes. "
                "Vent på avstemming eller kontroller ordren manuelt hos Saxo."
            )
        result = recover_stale_reserved_v3(
            instance_id=e.instance_id, request_key=pending["request_key"],
            db_path=db_path, broker=broker, now=now,
        )
        return InstanceResetResultV3(
            "RESERVATION_RECOVERED",
            result + " LIVE-tilstand og strategikonfigurasjon er bevart. "
                     "Neste ordinære signal vurderes av workeren."
        )

    # A no-pending check must never erase a previous order/strategy decision.
    # Verify broker context and active orders for an informative, nonmutating
    # result; repeated reads reduce the chance of a misleading stale snapshot.
    broker = broker if broker is not None else configured_live_pilot_client_v3()
    if broker is None:
        raise OrderRecoveryDeniedV3("Saxo LIVE er utilgjengelig. Reset er sperret.")
    account_key, _ = broker._account_context_exact(e.account_id)
    before = float(broker.signed_inventory_exact(
        account_id=e.account_id, uic=e.uic, asset_type=e.asset_type))
    if not isfinite(before):
        raise OrderRecoveryDeniedV3("Ugyldig Saxo-posisjon. Reset er sperret.")
    _assert_no_working_orders_v3(
        broker, account_id=e.account_id, account_key=account_key,
        uic=e.uic, asset_type=e.asset_type,
    )
    after = float(broker.signed_inventory_exact(
        account_id=e.account_id, uic=e.uic, asset_type=e.asset_type))
    if not isfinite(after) or abs(before - after) > 1e-8:
        raise OrderRecoveryDeniedV3("Saxo-posisjonen endret seg under kontrollen.")
    # Fail closed if a live worker concurrently reserved an order. No claims
    # that the system is clear or safe to issue a new order.
    latest = pending_order_v3(
        account_id=e.account_id, uic=e.uic, asset_type=e.asset_type,
        db_path=db_path,
    )
    if latest is not None:
        raise OrderRecoveryDeniedV3(
            "Ny ordre oppstod under kontrollen. Avstemming pågår."
        )
    return InstanceResetResultV3(
        "ALREADY_CLEAR",
        "Ingen uavklart V3-ordre eller aktiv Saxo-ordre på kontoen. "
        "Ingen historikk ble slettet. Eksisterende strategi og LIVE-tilstand "
        "er uendret; workeren evaluerer videre på nye signaler."
    )


__all__ = ["InstanceResetResultV3", "reset_instance_safely_v3"]
