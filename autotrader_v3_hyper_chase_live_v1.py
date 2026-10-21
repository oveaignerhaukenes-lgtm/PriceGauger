"""HyperVigilant 10s V3 LIVE signal adapter (broker-free).

Only freshly captured, exact-UIC, tradable Saxo bid/ask may form a signal.
The target may change LONG->SHORT without strategic cooldown, but ordinary
V3 execution still CLOSES first, reconciles Saxo FLAT, then evaluates a new
fresh quote before any opposite OPEN. There is no atomic net-cross claim.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from math import isfinite

from database import connect
from autotrader_v3_closed_bar_driver_v1 import ClosedBarDecisionV3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramDecisionV3
from live_sim_hyper_chase_10s_v1 import (
    ARMS,chase_signal_v1,MAX_QUOTE_AGE_SECONDS,MAX_FEED_GAP_SECONDS,
)
from live_sim_hyper_quotes_v1 import _utc

FAST_CATALOG_KEY="hyper-chase-10s-fast"
FILTERED_CATALOG_KEY="hyper-chase-10s-filtered"
FAST_RUNTIME_KEY="hyper-chase-10s-fast-v1"
FILTERED_RUNTIME_KEY="hyper-chase-10s-filtered-v1"
HYPER_CATALOG_KEYS=frozenset((FAST_CATALOG_KEY,FILTERED_CATALOG_KEY))
HYPER_RUNTIME_KEYS=frozenset((FAST_RUNTIME_KEY,FILTERED_RUNTIME_KEY))


def _decision(*,strategy_key,amount,action,reason,stamp):
    return ClosedBarDecisionV3(
        f"quote10:{strategy_key}:{stamp}:{action}",
        MacdHistogramDecisionV3(
            TargetInventoryV3(float(amount)),action,reason,0.0),
        False,
    )


def evaluate_hyper_closed_bar_compat_v3(
    *,trader_id,observation,strategy_key,actual_inventory=0.,**kwargs):
    """Registry probe contract, never generates a synthetic candle LIVE trade."""
    del trader_id,observation,kwargs
    return _decision(strategy_key=strategy_key,amount=(0. if actual_inventory is None else actual_inventory),
        action="WAIT_FRESH_QUOTE",reason="Live signals require genuine Saxo 1s BBO",
        stamp="no-quote")


def _ensure_state(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_hyper_chase_context(
        trader_id TEXT PRIMARY KEY,
        strategy_key TEXT NOT NULL,
        account_uic INTEGER NOT NULL,
        activated_at TEXT NOT NULL
    )""")


def evaluate_hyper_chase_live_v3(*,trader_id:str,strategy_key:str,
    account_uic:int,actual_amount:float,tranche:float,
    context_changed:bool,db_path="pricegauger.db",now=None):
    """Fresh-only, bounded quote decision. No Saxo HTTP or order code here."""
    if strategy_key not in HYPER_CATALOG_KEYS:
        raise ValueError("Unknown HyperVigilant LIVE strategy")
    clock=_utc(now or datetime.now(timezone.utc))
    current=float(actual_amount)
    def hold(action,why,stamp="unavailable"):
        return _decision(strategy_key=strategy_key,amount=current,
                         action=action,reason=why,stamp=stamp)

    try:
        with connect(db_path) as db:
            _ensure_state(db)
            row=db.execute("""SELECT strategy_key,account_uic,activated_at
                FROM pg_v3_hyper_chase_context WHERE trader_id=?""",
                (trader_id,)).fetchone()
            if (row is None or context_changed or
                str(row["strategy_key"])!=strategy_key or
                int(row["account_uic"])!=int(account_uic)):
                db.execute("""INSERT INTO pg_v3_hyper_chase_context
                    (trader_id,strategy_key,account_uic,activated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(trader_id) DO UPDATE SET
                    strategy_key=excluded.strategy_key,
                    account_uic=excluded.account_uic,
                    activated_at=excluded.activated_at""",
                    (trader_id,strategy_key,int(account_uic),clock.isoformat()))
                return hold("BOOTSTRAP","10-second fresh-quote warmup after activation")
            activated=_utc(row["activated_at"])
            if not timedelta(seconds=10)<=clock-activated<=timedelta(days=30):
                return hold("WAIT_WARMUP","No live opening until 10s after arming/context switch")
            # Bind to exact Saxo UIC. Never substitute nearest market or other
            # account's quote stream. No interpolated/cached REST prices.
            data=db.execute("""SELECT quote_at,bid,ask,received_at
                FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
                ORDER BY quote_at""",(
                  int(account_uic),(clock-timedelta(seconds=11)).isoformat(),
                  clock.isoformat())).fetchall()
    except Exception:
        return hold("NO_QUOTE_SOURCE","1s Saxo BBO table unavailable: no LIVE entry")

    if len(data)<9:
        return hold("NEED_QUOTES","Fewer than nine genuine BBO updates in 10s")
    try:
        end=data[-1]
        quote_at=_utc(end["quote_at"])
        received=_utc(end["received_at"])
        age=(clock-quote_at).total_seconds()
        transit=(received-quote_at).total_seconds()
        if not (0<=age<=MAX_QUOTE_AGE_SECONDS and -2<=transit<=MAX_QUOTE_AGE_SECONDS):
            return hold("STALE_QUOTES","Saxo quote is too old/future/delayed",
                        quote_at.isoformat())
        bid,ask=float(end["bid"]),float(end["ask"])
        if not (0<bid<=ask and isfinite(bid) and isfinite(ask)):
            return hold("BAD_BBO","Saxo bid/ask invalid",quote_at.isoformat())
        samples=[]
        for row in data:
            q_at=_utc(row["quote_at"])
            q_received=_utc(row["received_at"])
            if not -2<=(q_received-q_at).total_seconds()<=MAX_QUOTE_AGE_SECONDS:
                return hold("STALE_QUOTES","Delayed quote inside 10s signal",
                            quote_at.isoformat())
            b,a=float(row["bid"]),float(row["ask"])
            if not (0<b<=a and isfinite(b) and isfinite(a)):
                return hold("BAD_BBO","Invalid quote inside 10s signal",
                            quote_at.isoformat())
            samples.append((q_at.isoformat(),(b+a)/2))
    except (ValueError,TypeError,KeyError,OverflowError):
        return hold("BAD_QUOTE","Malformed Saxo BBO: no LIVE entry")

    arm=ARMS[0] if strategy_key==FAST_CATALOG_KEY else ARMS[1]
    signal,reason,evidence=chase_signal_v1(
        samples,at=quote_at,bid=bid,ask=ask,arm=arm)
    if not signal:
        # No synthetic FLAT signal on missing momentum: the normal V3
        # authority/risk manager remains owner of already-open inventory.
        return hold("WAIT_"+reason,reason+"; no new entry",
                    quote_at.isoformat())
    wanted=signal*float(tranche)
    direction="LONG" if signal>0 else "SHORT"
    return _decision(
        strategy_key=strategy_key,amount=wanted,
        action="CHASE_"+direction,
        reason=(f"live Saxo UIC={int(account_uic)} "
                f"10s={evidence.get('move_10s_bps')}bp, "
                f"threshold={evidence.get('threshold_bps')}bp; "
                "target flips immediately; Saxo execution is reconcile-first"),
        stamp=quote_at.isoformat(),
    )


def live_hyper_quote_cursors_v3(*,db_path="pricegauger.db",now=None):
    """DB-only 1s waking for explicitly LIVE-armed HyperVigilant instances."""
    from autotrader_v3_runtime_instances_v1 import load_v3_runtime_instances_v1
    from autotrader_v3_config_v1 import load_autotrader_config_v3
    from autotrader_v3_live_authority_v1 import live_authority_armed_v3
    from autotrader_engine_account_ownership_v1 import load_account_owner_v1,ENGINE_V3
    uics=set()
    try:
        for inst in load_v3_runtime_instances_v1(db_path=db_path):
            cfg=load_autotrader_config_v3(inst.pilot_key,db_path=db_path)
            if cfg.strategy_key not in HYPER_CATALOG_KEYS:
                continue
            if not live_authority_armed_v3(inst.pilot_key,db_path=db_path):
                continue
            owner=load_account_owner_v1(inst.account_id,db_path=db_path)
            if owner is None or owner.engine_id!=ENGINE_V3 or owner.owner_key!=inst.pilot_key:
                continue
            uics.add(int(inst.uic))
    except Exception:
        return ()
    if not uics:
        return ()
    clock=_utc(now or datetime.now(timezone.utc))
    result=[]
    try:
        with connect(db_path) as db:
            for uic in sorted(uics):
                row=db.execute("""SELECT MAX(quote_at) AS newest
                    FROM lsim_hyper_quotes_1s
                    WHERE provider_uic=? AND quote_at>=? AND quote_at<=?""",
                    (uic,(clock-timedelta(seconds=15)).isoformat(),
                     clock.isoformat())).fetchone()
                if row and row["newest"]:
                    result.append((uic,str(row["newest"])))
    except Exception:
        return ()
    return tuple(result)


__all__=["FAST_CATALOG_KEY","FILTERED_CATALOG_KEY",
         "FAST_RUNTIME_KEY","FILTERED_RUNTIME_KEY",
         "HYPER_CATALOG_KEYS","HYPER_RUNTIME_KEYS",
         "evaluate_hyper_chase_live_v3",
         "evaluate_hyper_closed_bar_compat_v3",
         "live_hyper_quote_cursors_v3"]
