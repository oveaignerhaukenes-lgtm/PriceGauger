"""Durable, broker-free Hunter/Rabid Dog V3 tick LIVE signal adapters.

The existing SHADOW signal semantics remain the decision model; ONLY genuine,
recent, tradable exact-UIC bid/ask from the canonical 1s capture are inputs.
No new Saxo requests, account arming, orders, or direct netting. V3 owns those.
State is committed as JSON per trader to survive worker restart/reconciliation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import fields
from datetime import datetime, timedelta, timezone
import json
from math import isfinite

from autotrader_hunter_v1 import Hunter
from autotrader_rabid_dog_v1 import RabidDog, RabidDogConfig
from autotrader_v3_closed_bar_driver_v1 import ClosedBarDecisionV3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramDecisionV3
from database import connect
from live_sim_hyper_quotes_v1 import _utc

HUNTER_CATALOG_KEY = "hunter-tick-v1"
DOG_CATALOG_KEY = "rabid-dog-tick-v1"
HUNTER_RUNTIME_KEY = "hunter-tick-live-v1"
DOG_RUNTIME_KEY = "rabid-dog-tick-live-v1"
TICK_CATALOG_KEYS = frozenset({HUNTER_CATALOG_KEY, DOG_CATALOG_KEY})
TICK_RUNTIME_KEYS = frozenset({HUNTER_RUNTIME_KEY, DOG_RUNTIME_KEY})
TICK_LIVE_UIC = 4912
MAX_QUOTE_AGE_S = 5
MAX_TRANSIT_S = 5
MAX_TICKS_PER_CYCLE = 30
BROKER_ORDERS_PER_HOUR = 24  # <= 12 full CLOSE/OPEN reversals per hour
SHADOW_DOG_EVENTS_PER_HOUR = 16  # shadow transitions may be 2 real orders
_DT_FIELDS = {
    HUNTER_CATALOG_KEY: {"last_extreme_at", "last_exit_at"},
    DOG_CATALOG_KEY: {"last_at"},
}
_DEQUE_FIELDS = {
    HUNTER_CATALOG_KEY: {"samples"},
    DOG_CATALOG_KEY: {"recent_moves", "order_times"},
}


def _decision(key, amount, action, reason, at):
    return ClosedBarDecisionV3(
        "tick:"+key+":"+str(at)+":"+action,
        MacdHistogramDecisionV3(TargetInventoryV3(float(amount)),action,reason,0.0),
        False,
    )


def evaluate_tick_closed_bar_compat_v3(*,strategy_key,actual_inventory=None,**_):
    return _decision(
        strategy_key,actual_inventory or 0.0,"WAIT_BBO",
        "True Saxo exact-UIC 1s BBO required, not OHLC candles","no-quote")


def _encode_model(key, model):
    payload = {}
    for field in fields(model):
        if field.name == "config":
            continue
        value = getattr(model, field.name)
        if field.name in _DT_FIELDS[key]:
            payload[field.name] = value.isoformat() if value else None
        elif field.name in _DEQUE_FIELDS[key]:
            if field.name == "samples":
                payload[field.name] = [[t.isoformat(), price] for t, price in value]
            elif field.name == "order_times":
                payload[field.name] = [t.isoformat() for t in value]
            else:
                payload[field.name] = list(value)
        else:
            payload[field.name] = value
    return json.dumps(payload, separators=(",",":"), allow_nan=False)


def _decode_model(key, raw):
    model = _new_model(key)
    data = json.loads(raw)
    if not isinstance(data,dict):
        raise ValueError("invalid tick state")
    for field in fields(model):
        name=field.name
        if name=="config":
            continue
        if name not in data:
            raise ValueError("incomplete tick state")
        val=data[name]
        if name in _DT_FIELDS[key]:
            val=_utc(val) if val else None
        elif name in _DEQUE_FIELDS[key]:
            if not isinstance(val,list) or len(val)>180:
                raise ValueError("unbounded tick state")
            if name=="samples":
                val=deque((_utc(t),float(mid)) for t,mid in val)
            elif name=="order_times":
                val=deque(_utc(t) for t in val)
            else:
                val=deque(float(v) for v in val)
        setattr(model,name,val)
    if model.target not in {"LONG","SHORT","FLAT"}:
        raise ValueError("invalid persisted target")
    return model


def _new_model(key):
    if key==HUNTER_CATALOG_KEY:
        return Hunter()
    if key==DOG_CATALOG_KEY:
        return RabidDog(RabidDogConfig(
            units=.01,orders_per_hour=SHADOW_DOG_EVENTS_PER_HOUR))
    raise ValueError("unsupported tick strategy")


def _ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_tick_live_state(
        trader_id TEXT PRIMARY KEY,
        strategy_key TEXT NOT NULL,
        provider_uic INTEGER NOT NULL,
        last_quote_at TEXT NOT NULL,
        last_signal_at TEXT,
        state_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


def _bootstrap(model, amount, when, bid, ask):
    mid=(bid+ask)/2
    side="LONG" if amount>0 else "SHORT" if amount<0 else "FLAT"
    model.target=side
    if isinstance(model,Hunter):
        model.samples=deque(((when,mid),))
        if side!="FLAT":
            model.impulse_origin=mid
            model.extreme=mid
            model.last_extreme_at=when
    else:
        model.last_at=when
        model.last_mid=mid
        model.anchor=model.extreme=mid
        model.entry_price=(ask if side=="LONG" else bid if side=="SHORT" else None)


def _broker_quota_remaining(db,trader_id,clock):
    # Durable V3 reservations, not the SHADOW model's hypothetical order count.
    # Count also UNKNOWN/SUBMITTING so crashes never reset the LIVE budget.
    # updated_at is SQLite and Postgres CURRENT_TIMESTAMP text in UTC.
    since=(clock-timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    count=db.execute("""SELECT COUNT(*) AS n FROM autotrader_v3_order_guard
        WHERE trader_id=? AND updated_at>=?""",
        (str(trader_id),since)).fetchone()
    used=int(count["n"])
    return max(0,BROKER_ORDERS_PER_HOUR-used)


def evaluate_tick_live_v3(*,trader_id, strategy_key, account_uic,
    asset_type,actual_amount,tranche,context_changed=False,
    db_path="pricegauger.db",now=None):
    """Run one new quote window against durable model state; fail closed.

    Missing quotes always HOLD actual inventory; fresh FLAT targets may CLOSE.
    Expansion requires a NEW model signal <=5s and broker-side order budget.
    """
    current=float(actual_amount)
    clock=_utc(now or datetime.now(timezone.utc))
    if strategy_key not in TICK_CATALOG_KEYS:
        raise ValueError("unknown tick LIVE model")
    def hold(action,why,stamp="unavailable"):
        return _decision(strategy_key,current,action,why,stamp)

    if int(account_uic)!=TICK_LIVE_UIC or str(asset_type)!="CfdOnIndex":
        return hold("BLOCK_PRODUCT","Hunter/Rabid require exact Tech100 CfdOnIndex UIC 4912")
    if abs(current)>float(tranche)+1e-9:
        return hold("BLOCK_SIZE","Tick strategies cannot manage oversized inventory automatically")
    try:
        with connect(db_path) as db:
            _ensure_schema(db)
            row=db.execute("""SELECT strategy_key,provider_uic,last_quote_at,last_signal_at,state_json
                FROM pg_v3_tick_live_state WHERE trader_id=?""",(str(trader_id),)).fetchone()
            reset=(row is None or context_changed or
                row["strategy_key"]!=strategy_key or int(row["provider_uic"])!=int(account_uic))
            last_at=None if reset else _utc(row["last_quote_at"])
            lower=(clock-timedelta(seconds=12)) if last_at is None else max(
                clock-timedelta(seconds=12),last_at)
            quotes=db.execute("""SELECT quote_at,received_at,bid,ask
                FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND quote_at>? AND quote_at<=?
                ORDER BY quote_at LIMIT ?""",(
                int(account_uic),lower.isoformat(),clock.isoformat(),
                MAX_TICKS_PER_CYCLE)).fetchall()
            if not quotes:
                return hold("WAIT_QUOTES","No new genuine 1s Saxo quote")
            latest=_utc(quotes[-1]["quote_at"])
            if not 0<=(clock-latest).total_seconds()<=MAX_QUOTE_AGE_S:
                return hold("WAIT_STALE","BBO stream is not fresh")
            clean=[]
            for q in quotes:
                at,received=_utc(q["quote_at"]),_utc(q["received_at"])
                bid,ask=float(q["bid"]),float(q["ask"])
                if not (0<bid<=ask and isfinite(bid) and isfinite(ask) and
                    -2<=(received-at).total_seconds()<=MAX_TRANSIT_S):
                    return hold("WAIT_BAD_BBO","Untrusted BBO sample")
                clean.append((at,bid,ask))
            if reset:
                model=_new_model(strategy_key)
                _bootstrap(model,current,latest,clean[-1][1],clean[-1][2])
                signal_at=None
            else:
                model=_decode_model(strategy_key,row["state_json"])
                signal_at=_utc(row["last_signal_at"]) if row["last_signal_at"] else None
            newest_decision=None
            gap_exit=False
            if not reset:
                for at,bid,ask in clean:
                    # Never bridge a stale/unobserved interval with invented ticks.
                    if last_at is not None and (at-last_at).total_seconds()>5:
                        # Reset to broker-confirmed inventory, never replay an
                        # old desired direction across a network/feed outage.
                        model=_new_model(strategy_key)
                        # Preserve original Rabid Dog's explicit quote-gap FLAT
                        # policy. Hunter's shadow policy instead HOLDS on a gap.
                        gap_exit = gap_exit or (strategy_key==DOG_CATALOG_KEY and abs(current)>1e-12)
                        _bootstrap(model,0. if strategy_key==DOG_CATALOG_KEY else current,
                                   at,bid,ask)
                        signal_at=None
                        newest_decision=None
                        last_at=at
                        continue
                    new=model.on_quote(at,bid,ask)
                    last_at=at
                    if new is not None:
                        newest_decision=new
                        signal_at=at
            db.execute("""INSERT INTO pg_v3_tick_live_state(
                trader_id,strategy_key,provider_uic,last_quote_at,last_signal_at,state_json,updated_at)
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(trader_id) DO UPDATE SET
                    strategy_key=excluded.strategy_key,provider_uic=excluded.provider_uic,
                    last_quote_at=excluded.last_quote_at,
                    last_signal_at=excluded.last_signal_at,
                    state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP""",
                (str(trader_id),strategy_key,int(account_uic),latest.isoformat(),
                 signal_at.isoformat() if signal_at else None,_encode_model(strategy_key,model)))
            if reset:
                return hold("BOOTSTRAP","State reset on account/strategy switch; wait for new quotes",latest.isoformat())
            if gap_exit:
                return _decision(strategy_key,0.,"QUOTE_GAP_FLAT",
                    "Rabid Dog BBO gap >5s; close only, never open",latest.isoformat())
            side={"LONG":float(tranche),"SHORT":-float(tranche),"FLAT":0.0}[model.target]
            # A signal can justify closing exposure after a direction change,
            # but NOT re-opening on a stale decision after Saxo reconciliation.
            if abs(side)>abs(current)+1e-10 or side*current<0:
                fresh=signal_at is not None and 0<=(clock-signal_at).total_seconds()<=5
                if not fresh:
                    # The old direction may safely CLOSE, but a new position
                    # requires a fresh causal impulse after Saxo FLAT.
                    if side*current<0 and abs(current)>1e-12:
                        return _decision(strategy_key,0,"STALE_REVERSAL_FLAT",
                            "Opposite signal too old for new entry; flatten first",latest.isoformat())
                    return hold("WAIT_FRESH_SIGNAL","No new price impulse for opening",latest.isoformat())
                # Count durable reservations, not shadow signals; preserve one
                # possible CLOSE even if an open/flip consumes the hourly cap.
                remaining=_broker_quota_remaining(db,trader_id,clock)
                if remaining<2:
                    if side*current<0 and abs(current)>1e-12:
                        return _decision(strategy_key,0,"QUOTA_FLAT",
                            "Cap reached; reduction only",latest.isoformat())
                    return hold("WAIT_BROKER_QUOTA",
                        "Conservative real V3 order reservation/hour cap",latest.isoformat())
            label=newest_decision.reason if newest_decision else "MODEL_HOLD"
            return _decision(strategy_key,side,
                "TICK_"+model.target if newest_decision else "HOLD_"+model.target,
                "genuine new Saxo BBO; "+label+
                "; LIVE still subject to V3 Saxo precheck and FLAT reconciliation",
                latest.isoformat())
    except Exception:
        return hold("WAIT_TICK_STATE","BBO/state/quota unavailable; no new exposure")
