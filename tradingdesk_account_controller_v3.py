"""Read-only, deterministic engine/controller identity for TradingDesk.

Registry and explicit account ownership are authoritative for V3. Historical
V2 enrollments are *not* a sufficient source to call a Saxo account "free".
A conflict disables both engine panels; it never transfers ownership.
"""
from __future__ import annotations

from dataclasses import dataclass

from autotrader_engine_identity_v1 import ENGINE_V2,ENGINE_V3,enrollment_engine_v1


@dataclass(frozen=True, slots=True)
class AccountControllerTruthV1:
    account_id: str
    engine: str | None
    instance: object | None
    enrollment: object | None
    owner: object | None
    conflict: str | None


def account_controller_truth_v1(account_ids, *, instances, owners, enrollments):
    """Resolve all accounts in one pass; fail closed on conflicting identity.

    Instances: enabled canonical V3 registry only; owner must match exact
    account and instance identity when claimed; enrollment is legacy fallback.
    """
    ids=set(str(a) for a in account_ids)
    reg={}
    for inst in instances:
        aid=str(inst.account_id)
        if aid in reg:
            raise ValueError("multiple enabled V3 instances for one Saxo account")
        reg[aid]=inst
    legacy={}
    for item in enrollments:
        if not item.enabled or item.execution_mode!="LIVE_MANAGE":
            continue
        legacy.setdefault(str(item.account_id),[]).append(item)
    out={}
    for aid in ids:
        inst=reg.get(aid)
        owner=owners.get(aid)
        enrs=legacy.get(aid,[])
        conflict=None
        if len(enrs)>1:
            conflict="Flere aktive historiske LIVE-enrollments for samme konto"
        enrollment=enrs[0] if len(enrs)==1 else None
        old_engine=enrollment_engine_v1(enrollment) if enrollment is not None else None
        owner_engine=str(owner.engine_id).strip().upper() if owner is not None else None
        if owner_engine not in (None,ENGINE_V2,ENGINE_V3):
            conflict="Ukjent lagret execution-eierskap"
        if inst is not None and owner_engine not in (None,ENGINE_V3):
            conflict="V3-instansen kolliderer med execution-eierskap for annen motor"
        if inst is not None and owner_engine==ENGINE_V3 and str(owner.owner_key)!=str(inst.instance_id):
            conflict="V3-instansens pilot-ID samsvarer ikke med execution-eierskapet"
        if owner_engine==ENGINE_V2 and enrollment is not None and old_engine==ENGINE_V3:
            conflict="Historisk V3-enrollment kolliderer med V2-eierskap"
        if owner_engine==ENGINE_V3 and inst is None and enrollment is not None and str(owner.owner_key)!=str(enrollment.pilot_key):
            conflict="V3-eierskap samsvarer ikke med historisk pilot-ID"
        # A legacy strategy-family heuristic can classify modern V3 configs
        # as V2; exact registry/owner must take priority.
        engine=owner_engine or (ENGINE_V3 if inst is not None else old_engine)
        out[aid]=AccountControllerTruthV1(aid,engine,inst,enrollment,owner,conflict)
    return out
