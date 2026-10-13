"""Operator-confirmed recovery of provably unsubmitted V3 RESERVED intents.

Fail closed for SUBMITTING, SUBMITTED and UNKNOWN: those may have reached Saxo.
No broker POST, no deletion, no position changes and no implicit recovery.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hmac import compare_digest
from math import isfinite
import os

from database import connect
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_order_guard_v1 import pending_order as pending_order_v3
from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3

MIN_STALE_SECONDS = 120


class OrderRecoveryDeniedV3(RuntimeError):
    """An unverified order reservation must remain locked."""


def _timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def recovery_eligibility_v3(*, pending, actual, now=None):
    """Pure, strict eligibility for a stale unsubmitted RESERVED intent."""
    if pending is None or str(pending.get("state")) != "RESERVED":
        return False, "Kun RESERVED kan frigjøres automatisk; Saxo-avstemming kreves."
    if pending.get("broker_order_id"):
        return False, "Ordren har Saxo-ID; den kan ikke resettes her."
    stamp = _timestamp(pending.get("updated_at"))
    current = now or datetime.now(timezone.utc)
    if stamp is None or (current.astimezone(timezone.utc) - stamp).total_seconds() < MIN_STALE_SECONDS:
        return False, "Reservasjonen er for ny eller mangler sikkert tidsstempel."
    try:
        qty = float(pending["submitted_amount"])
        expected = float(pending["expected_inventory"])
        side = str(pending["submitted_side"]).lower()
        actual = float(actual)
        if side not in {"buy", "sell"} or not all(map(isfinite, (qty, expected, actual))) or qty <= 0:
            raise ValueError()
        pre_order = expected - (qty if side == "buy" else -qty)
    except (TypeError, ValueError, KeyError):
        return False, "Ugyldig eller manglende ordrehistorikk."
    if abs(actual - pre_order) > 1e-8:
        return False, "Saxos posisjon avviker fra posisjonen før ordren."
    return True, "Stale RESERVED med uendret Saxo-posisjon."


def _assert_no_working_orders_v3(broker, *, account_id, account_key, uic, asset_type):
    """Require an exhaustive broker read, with no unverified same-account order."""
    payload = broker.client._get("port/v1/orders/me", params={"$top": 1000})
    if not isinstance(payload, dict) or payload.get("__next") or not isinstance(payload.get("Data"), list):
        raise OrderRecoveryDeniedV3("Saxo aktiv ordreliste er utilgjengelig/ufullstendig.")
    for order in payload["Data"]:
        if not isinstance(order, dict):
            raise OrderRecoveryDeniedV3("Saxo ordreliste inneholder ugyldig oppføring.")
        order_account = str(order.get("AccountId") or "").strip()
        order_key = str(order.get("AccountKey") or "").strip()
        if not order_account and not order_key:
            raise OrderRecoveryDeniedV3("Saxo aktiv ordre mangler verifiserbar konto.")
        if order_account == account_id or order_key == account_key:
            # This can be overly conservative for another instrument, deliberately.
            raise OrderRecoveryDeniedV3("Saxo har aktiv ordre på samme konto; behold låsen.")


def recover_stale_reserved_v3(*, instance_id, request_key, operator_pin, db_path="pricegauger.db", broker=None, now=None):
    """Release exactly one pre-submit reservation with human operator authority.

    An explicit Railway-only secret is required. This path never places an order.
    """
    secret = os.environ.get("PG_V3_ORDER_RECOVERY_PIN", "")
    if len(secret) < 12 or not compare_digest(str(operator_pin or ""), secret):
        raise OrderRecoveryDeniedV3("Manglende/ugyldig operatørkode for ordreavstemming.")
    instances = tuple(i for i in load_v3_instances_v1(db_path=db_path) if i.instance_id == str(instance_id))
    if len(instances) != 1:
        raise OrderRecoveryDeniedV3("Finner ikke nøyaktig én aktiv V3-instans.")
    instance = instances[0]
    pending = pending_order_v3(account_id=instance.account_id, uic=instance.uic, asset_type=instance.asset_type, db_path=db_path)
    if pending is None or pending["request_key"] != str(request_key):
        raise OrderRecoveryDeniedV3("Ordre-ID eller reservasjon er endret; oppdater status først.")
    if pending["state"] != "RESERVED" or pending.get("broker_order_id"):
        raise OrderRecoveryDeniedV3("Kan bare frigjøre gammel RESERVED uten Saxo-ordre-ID.")
    broker = broker if broker is not None else configured_live_pilot_client_v3()
    if broker is None:
        raise OrderRecoveryDeniedV3("Saxo LIVE er utilgjengelig; behold låsen.")
    # Exact broker account/instrument, independently refreshed.
    account_key, _ = broker._account_context_exact(instance.account_id)
    actual = broker.signed_inventory_exact(account_id=instance.account_id, uic=instance.uic, asset_type=instance.asset_type)
    ok, message = recovery_eligibility_v3(pending=pending, actual=actual, now=now)
    if not ok:
        raise OrderRecoveryDeniedV3(message)
    _assert_no_working_orders_v3(broker, account_id=instance.account_id, account_key=account_key, uic=instance.uic, asset_type=instance.asset_type)
    # Recheck actual after inspecting orders; refuse to unlock on an external fill.
    actual2 = broker.signed_inventory_exact(account_id=instance.account_id, uic=instance.uic, asset_type=instance.asset_type)
    ok, message = recovery_eligibility_v3(pending=pending, actual=actual2, now=now)
    if not ok:
        raise OrderRecoveryDeniedV3(message)
    # Compare-and-swap: a LIVE worker must also use CAS to claim SUBMITTING,
    # preventing an in-flight worker from posting after an operator recovery.
    with connect(db_path) as db:
        cursor = db.execute("""UPDATE autotrader_v3_order_guard
            SET state='REJECTED', detail='OPERATOR_RECOVERED_PRE_SUBMIT_RESERVED; exact Saxo inventory and working orders verified',
                updated_at=CURRENT_TIMESTAMP
            WHERE request_key=? AND trader_id=? AND account_id=? AND uic=? AND asset_type=?
              AND state='RESERVED' AND broker_order_id IS NULL AND updated_at=?""",
            (str(request_key), instance.instance_id, instance.account_id, int(instance.uic),
             instance.asset_type, pending["updated_at"]))
        if cursor.rowcount != 1:
            raise OrderRecoveryDeniedV3("Reservasjonen ble endret under kontrollen; ingen reset utført.")
    return f"{instance.instance_id}: gammel RESERVED frigjort etter Saxo-verifikasjon. Ingen ordre sendt."


__all__ = ["recover_stale_reserved_v3", "recovery_eligibility_v3", "OrderRecoveryDeniedV3"]
