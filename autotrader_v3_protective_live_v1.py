"""Opt-in V3 LIVE protective modifiers, no broker order authority.

Impulse guard: exact Saxo UIC captured 1s BBO, 10s adverse returns, rolling
robust reference; persistent pause and hysteresis. Account drawdown latch:
fresh exact Saxo account TotalValue with independently verified currency,
10% peak-to-trough circuit breaker. Both produce only approved target intents.
The unmodified V3 order guard / ownership / risk cap / Saxo reconcile performs
every CLOSE, and can fail or slip beyond a proposed 10% trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median
from typing import Mapping, Sequence

from autotrader_v3_domain import TargetInventoryV3
from database import connect

IMPULSE_LOOKBACK_S = 80
IMPULSE_WINDOW_S = 10
MAX_STALE_SECONDS = 5
IMPULSE_ABS_MIN_BPS = 9.0
IMPULSE_MULTIPLIER = 3.0
IMPULSE_QUIET_SECONDS = 25
DRAWDOWN_WARN_PCT = 5.
DRAWDOWN_NO_ADD_PCT = 8.
DRAWDOWN_FLAT_PCT = 10.


def utc(v):
    t = v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("aware timestamps required")
    return t.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProtectiveEvidenceV3:
    code: str
    status: str
    reason: str
    move_bps: float | None = None
    threshold_bps: float | None = None
    drawdown_pct: float | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ProtectiveModifierV3:
    key: str
    evidence: ProtectiveEvidenceV3
    actual_inventory: float

    def apply(self, trader, target: TargetInventoryV3):
        current=float(self.actual_inventory)
        wanted=float(target.amount)
        status=self.evidence.status
        if status in ("IMPULSE_PAUSE","DRAWDOWN_LOCK"):
            return TargetInventoryV3(0.),self.evidence.reason+"; protective target FLAT"
        if status in ("DATA_MISSING","DRAWDOWN_NO_ADD"):
            # Missing safety evidence or early drawdown: never increase exposure.
            if abs(current)>1.e-9 and wanted*current<0:
                return TargetInventoryV3(0.),"protective opposite -> FLAT"
            if abs(wanted)>abs(current)+1.e-9:
                return TargetInventoryV3(current),self.evidence.reason+"; veto OPEN/ADD"
        return target,self.evidence.reason


def ensure_risk_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_protective_state(
            trader_id TEXT NOT NULL, modifier_key TEXT NOT NULL,
            context TEXT NOT NULL, status TEXT NOT NULL, since_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, quiet_since TEXT, reference_value DOUBLE PRECISION,
            peak_value DOUBLE PRECISION, PRIMARY KEY(trader_id,modifier_key))""")


def _load(trader_id,key,db_path):
    ensure_risk_schema_v3(db_path)
    with connect(db_path) as db:
        row=db.execute("""SELECT context,status,since_at,updated_at,quiet_since,
            reference_value,peak_value FROM autotrader_v3_protective_state
            WHERE trader_id=? AND modifier_key=?""",(trader_id,key)).fetchone()
    return dict(row) if row else None


def _save(trader_id,key,context,status,at,quiet,reference,peak,db_path):
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_protective_state(
          trader_id,modifier_key,context,status,since_at,updated_at,
          quiet_since,reference_value,peak_value)
          VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(trader_id,modifier_key) DO UPDATE SET
          context=excluded.context,status=excluded.status,
          since_at=CASE WHEN autotrader_v3_protective_state.status<>excluded.status
                          OR autotrader_v3_protective_state.context<>excluded.context
                     THEN excluded.since_at ELSE autotrader_v3_protective_state.since_at END,
          updated_at=excluded.updated_at,quiet_since=excluded.quiet_since,
          reference_value=excluded.reference_value,peak_value=excluded.peak_value""",
          (trader_id,key,context,status,at.isoformat(),at.isoformat(),
           quiet.isoformat() if quiet else None,reference,peak))


def impulse_evidence_v3(*, rows:Sequence[Mapping], now:datetime,
                        actual_amount:float, was_paused:bool=False,
                        quiet_since:datetime|None=None) -> tuple[ProtectiveEvidenceV3,datetime|None]:
    """Fully observed BBO points, no interpolated or future/unreceived quotes."""
    clock=utc(now); samples=[];prev=None
    try:
        for row in rows:
            stamp=utc(row["quote_at"]); seen=utc(row["received_at"])
            bid=float(row["bid"]);ask=float(row["ask"])
            if (not 0<bid<=ask or not isfinite(bid) or not isfinite(ask)
                    or (prev is not None and stamp<=prev)
                    or (seen-stamp).total_seconds() > 5
                    or (seen-stamp).total_seconds() < -2
                    or seen>clock):
                return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","BBO out of order/delayed or future"),None
            samples.append((stamp,(bid+ask)/2,seen))
            prev=stamp
    except (KeyError,TypeError,ValueError,OverflowError):
        return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","invalid exact-UIC BBO"),None
    if len(samples)<25 or (clock-samples[-1][0]).total_seconds()>MAX_STALE_SECONDS:
        return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","insufficient/frozen BBO"),None
    last_at,last_mid,_=samples[-1]
    base=next((x for x in reversed(samples) if 9<=
               (last_at-x[0]).total_seconds()<=12),None)
    if base is None:
        return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","missing 10s quote anchor"),None
    old=base[1]
    if old<=0:
        return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","nonpositive BBO"),None
    move=10000*(last_mid/old-1)
    historical=[]
    for end_i in range(10,len(samples),5):
        entry=samples[end_i]
        previous=next((x for x in reversed(samples[:end_i])
                       if 9<=(entry[0]-x[0]).total_seconds()<=12),None)
        if previous is not None:
            historical.append(abs(10000*(entry[1]/previous[1]-1)))
    if len(historical)<4:
        return ProtectiveEvidenceV3("impulse-exit","DATA_MISSING","insufficient adaptive volatility baseline"),None
    threshold=max(IMPULSE_ABS_MIN_BPS,IMPULSE_MULTIPLIER*median(historical))
    adverse=float(actual_amount)*move<0
    shocked=abs(actual_amount)>1e-9 and adverse and abs(move)>=threshold
    if shocked:
        return ProtectiveEvidenceV3("impulse-exit","IMPULSE_PAUSE",
             "adverse 10s BBO impulse, guarded FLAT until calmer",
             round(move,3),round(threshold,3),observed_at=clock),None
    if was_paused:
        # Two conditions: no further strong impulse + monotonic quiet time.
        # Require quote direction to stop opposing inventory, OR a material
        # retrace of the adverse impulse (normal activity) for >=25sec.
        calm=abs(move)<threshold*.5
        quiet=quiet_since if quiet_since and calm else clock if calm else None
        if quiet is None or (clock-quiet).total_seconds()<IMPULSE_QUIET_SECONDS:
            return ProtectiveEvidenceV3("impulse-exit","IMPULSE_PAUSE",
                "cooldown/reversal confirmation pending",
                round(move,3),round(threshold,3),observed_at=clock),quiet
    return ProtectiveEvidenceV3("impulse-exit","CLEAR",
        "normal market impulse; base strategy controls reentry",
        round(move,3),round(threshold,3),observed_at=clock),None


def evaluate_impulse_live_v3(*,trader_id:str,context:str,uic:int,
                             actual_amount:float, now:datetime,db_path="pricegauger.db"):
    clock=utc(now)
    previous=_load(trader_id,"impulse-exit",db_path)
    if previous and previous["context"]!=context:
        previous=None
    from_at=clock-timedelta(seconds=IMPULSE_LOOKBACK_S)
    with connect(db_path) as db:
        data=db.execute("""SELECT quote_at,received_at,bid,ask
          FROM lsim_hyper_quotes_1s WHERE provider_uic=?
            AND quote_at>=? AND quote_at<=? ORDER BY quote_at LIMIT 120""",
            (int(uic),from_at.isoformat(),clock.isoformat())).fetchall()
    previous_paused=bool(previous and previous["status"]=="IMPULSE_PAUSE")
    # Missing quote data must never clear a previously triggered pause.
    previous_quiet=utc(previous["quiet_since"]) if previous and previous["quiet_since"] else None
    evidence,quiet=impulse_evidence_v3(
        rows=data,now=clock,actual_amount=actual_amount,
        was_paused=previous_paused,quiet_since=previous_quiet)
    if previous_paused and evidence.status=="DATA_MISSING":
        evidence=ProtectiveEvidenceV3("impulse-exit","IMPULSE_PAUSE",
                                     "BBO stale during protective pause; remain FLAT")
    _save(trader_id,"impulse-exit",context,evidence.status,clock,quiet,None,None,db_path)
    return evidence


def drawdown_evidence_v3(*,total_value:float|None,verified:bool,
                         peak_value:float|None,locked:bool=False):
    if locked:
        return ProtectiveEvidenceV3("account-loss-lock","DRAWDOWN_LOCK",
                                    "account peak drawdown lock latched; manual reset required")
    if (not verified or total_value is None or not isfinite(total_value)
            or total_value<=0 or peak_value is None or peak_value<=0):
        return ProtectiveEvidenceV3("account-loss-lock","DATA_MISSING",
                                    "exact Saxo account NAV/currency/reliability unverified")
    dd=100*(1-total_value/peak_value)
    if dd+1e-9>=DRAWDOWN_FLAT_PCT:
        status="DRAWDOWN_LOCK"
    elif dd+1e-9>=DRAWDOWN_NO_ADD_PCT:
        status="DRAWDOWN_NO_ADD"
    elif dd+1e-9>=DRAWDOWN_WARN_PCT:
        status="DRAWDOWN_WARN"
    else: status="CLEAR"
    return ProtectiveEvidenceV3("account-loss-lock",status,
             f"exact Saxo NAV high-water drawdown {dd:.2f}% (external cashflows not corrected)",
             drawdown_pct=round(dd,3))


def evaluate_account_loss_live_v3(*,trader_id:str,context:str,
                                  account:Mapping,broker,now:datetime,db_path="pricegauger.db"):
    from autotrader_saxo_account_truth_v1 import parse_saxo_balance_v1
    clock=utc(now)
    previous=_load(trader_id,"account-loss-lock",db_path)
    if previous and previous["context"]!=context:
        # New strategy/currency/account should NEVER quietly unlock an
        # existing risk breaker. Human reset in a separate guarded action.
        if previous["status"]=="DRAWDOWN_LOCK":
            return ProtectiveEvidenceV3("account-loss-lock","DRAWDOWN_LOCK",
                                        "previous risk lock persists across strategy switch")
        previous=None
    try:
        payload=broker.client._get("port/v1/balances",params={
            "AccountKey":str(account["AccountKey"]),
            "ClientKey":str(account["ClientKey"]),
        })
        snap=parse_saxo_balance_v1(account=account,payload=payload,observed_at=clock)
        verified=snap.verified and snap.total_value>0
        total=snap.total_value if verified else None
    except Exception:
        total=None;verified=False
    # Reuse fresh verified observation for at most 10s. This is an early
    # protective gate, not the slow 15-minute capital manager.
    if previous and previous["status"]=="DRAWDOWN_LOCK":
        return ProtectiveEvidenceV3("account-loss-lock","DRAWDOWN_LOCK",
                                    "persistent exact account risk lock; manual verified reset required")
    old_peak=float(previous["peak_value"]) if previous and previous["peak_value"] is not None else None
    old_locked=bool(previous and previous["status"]=="DRAWDOWN_LOCK")
    peak=max(old_peak,total) if old_peak is not None and total is not None else (old_peak or total)
    evidence=drawdown_evidence_v3(total_value=total,verified=verified,
                                 peak_value=peak,locked=old_locked)
    # Only persist verified observations, or existing state: unverified
    # initial snapshot doesn't establish an anchor or override a good one.
    if verified or previous:
        _save(trader_id,"account-loss-lock",context,evidence.status,clock,None,
              float(previous["reference_value"]) if previous and previous["reference_value"] else total,
              peak,db_path)
    return evidence


def reset_account_loss_lock_v3(*,trader_id:str,context:str,
                               account_id:str,uic:int,asset_type:str,
                               broker,now:datetime,db_path="pricegauger.db"):
    """Explicit human-only unlock after verified Saxo FLAT and good NAV.

    Never used by LIVE worker or timer. A disabled toggle is NOT a reset.
    """
    from autotrader_saxo_account_truth_v1 import parse_saxo_balance_v1
    clock=utc(now)
    previous=_load(trader_id,"account-loss-lock",db_path)
    if not previous or previous["status"]!="DRAWDOWN_LOCK":
        raise ValueError("no account drawdown lock to reset")
    if previous["context"]!=context:
        raise ValueError("account/product/currency changed; retain safety lock")
    actual=broker.signed_inventory_exact(
        account_id=account_id,uic=int(uic),asset_type=asset_type)
    if abs(float(actual))>1e-9:
        raise ValueError("Saxo exact position must be confirmed FLAT before manual unlock")
    matches=[x for x in broker.accounts()
             if str(x.get("AccountId") or "")==account_id]
    if len(matches)!=1:
        raise ValueError("unique Saxo account not verified")
    account=matches[0]
    payload=broker.client._get("port/v1/balances",params={
        "AccountKey":account["AccountKey"],"ClientKey":account["ClientKey"],
    })
    snap=parse_saxo_balance_v1(account=account,payload=payload,observed_at=clock)
    if not snap.verified or snap.total_value<=0:
        raise ValueError("verified positive exact Saxo NAV required")
    _save(trader_id,"account-loss-lock",context,"CLEAR",clock,None,
          snap.total_value,snap.total_value,db_path)
    return snap.total_value
