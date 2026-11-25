"""Conservative automatic *scenario* parameters from observed broker evidence.

No guesses for currency conversion, point value or fees. This only seeds a
forward trial, never declares parity. Freeze the result per session; a later
recalibration is a separate experiment. No broker calls in this module.
"""
from datetime import datetime,timedelta,timezone
from math import isfinite
from statistics import median
import json
from database import connect
from live_mirror_audit_v1 import calibration_samples
from live_mirror_validation_v1 import calibrate_fills
from live_mirror_registry_v1 import mirror_snapshot,_stamp


def derive_observed_terms(rows, calibration, *, uic, asset_type, required_sides=("BUY","SELL")):
    """First automatic scope: NOK, explicit zero-commission illustration.

    Nonzero or unavailable commission terms require further cost modelling.
    Broker estimates are not proof of booked funding or actual commissions.
    """
    multipliers=[];fractions=[];lots=[];sides=set()
    for p in rows:
        try:
            if int(p["uic"])!=int(uic) or p["asset_type"]!=asset_type:
                continue
            if p["account_currency"].upper()!="NOK" or p["margin_currency"].upper()!="NOK":
                continue
            if p["commission_currency"].upper()!="NOK" or p["long_commission"]!=0 or p["short_commission"]!=0:
                continue
            fx=1. if p["instrument_currency"].upper()=="NOK" else float(p["conversion_rate"])
            multiplier=float(p["contract_size"])*fx
            price=float(p["reference_price"]);amount=float(p["order_amount"])
            margin=float(p["initial_margin"]);lot=float(p["minimum_lots"])
            if not all(isfinite(x) and x>0 for x in (multiplier,price,amount,margin,lot)):
                continue
            fraction=margin/(price*amount*multiplier)
            if not 0<fraction<=1:
                continue
            side=str(p["side"]).upper()
            if side not in ("BUY","SELL"):
                continue
            multipliers.append(multiplier);fractions.append(fraction);lots.append(lot);sides.add(side)
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    if len(multipliers)<3 or not set(required_sides).issubset(sides) or len(set(lots))!=1:
        return None
    # Refuse changing contract/FX units rather than hiding a large mismatch.
    if max(multipliers)/min(multipliers)>1.05:
        return None
    latency=float(calibration.latency_p50)
    return dict(nok_per_point_per_lot=median(multipliers),
                margin_fraction=max(fractions),fee_nok_per_lot_per_side=0.,
                latency_seconds=latency,
                adverse_slippage_points=max(0.,float(calibration.slippage_p50)),
                minimum_lots=lots[0],max_quote_wait_seconds=max(10.,float(calibration.latency_p95)+2.))


def observed_scenario_terms(*,db_path="pricegauger.db",now=None):
    """Bounded recent evidence scan. Requires 30 exact fill/BBO samples per instrument."""
    now=now or datetime.now(timezone.utc)
    refs=mirror_snapshot(db_path=db_path) or ()
    by_instrument={}
    for r in refs:
        cfg=json.loads(r["config_json"])
        boundary=cfg["boundary"]
        key=str(boundary["uic"])+":"+boundary["asset_type"]
        try:
            samples,_=calibration_samples(instance_id=r["instance_id"],db_path=db_path,limit=60)
        except Exception:
            samples=()
        by_instrument.setdefault(key,[]).extend(s for s in samples
            if now-timedelta(days=7)<=s.filled_at<now)
    calibrated={}
    for key,samples in by_instrument.items():
        try:
            calibrated[key]=calibrate_fills(samples,frozen_at=now,minimum=30)
        except ValueError:
            pass
    result={}
    for r in refs:
        cfg=json.loads(r["config_json"])
        boundary=cfg["boundary"]
        key=str(boundary["uic"])+":"+boundary["asset_type"]
        if key not in calibrated:
            continue
        try:
            with connect(db_path) as db:
                rows=db.execute("""SELECT payload_json FROM pg_live_mirror_trace_v1
                  WHERE instance_id=? AND event_type='TERMS' AND observed_at>=?
                  ORDER BY observed_at DESC LIMIT 30""",
                  (r["instance_id"],(now-timedelta(days=1)).isoformat())).fetchall()
            strategy=cfg["strategy"]["strategy_key"]
            required=("BUY",) if "-long-flat-" in strategy else ("SELL",) if "-short-flat-" in strategy else ("BUY","SELL")
            terms=derive_observed_terms([json.loads(x["payload_json"]) for x in rows],
                calibrated[key],uic=boundary["uic"],asset_type=boundary["asset_type"],required_sides=required)
            if terms:
                result["instance:"+r["instance_id"]]=terms
        except (ValueError,TypeError,KeyError):
            continue
    return result
