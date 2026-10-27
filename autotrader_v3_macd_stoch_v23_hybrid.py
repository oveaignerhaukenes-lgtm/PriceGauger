"""V3 MACD+Stoch V2.3 Hybrid: fully closed 1m direction + genuine 15s BBO timing.

Read-only strategy signal producer. LIVE integration uses the unchanged
broker CLOSE -> CONFIRM_FLAT -> OPEN order plan. Never calls Saxo order APIs.

The macro direction uses V2.1's 70/30 composite score on two completed 1m
candles; micro entries/exit require consecutive *completed* genuine Saxo 15s
BBO bars with adequate coverage. Every last-15s-bar decision is persisted,
so a 1s worker wake cannot pyramid repeatedly on the same bar.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from math import isfinite

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2,macd_observations_v2
from autotrader_v3_macd_stoch_v2 import (
    composite_score_v3,ENTRY_THRESHOLD,EXIT_THRESHOLD,
)
from autotrader_v3_closed_bar_driver_v1 import ClosedBarDecisionV3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramDecisionV3
from macd_stoch_v21_30s_research_v1 import (
    Quote30V1,build_completed_bars_v1,validate_quotes_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect

CATALOG_KEY="macd-stoch-v2-3-hybrid"
RUNTIME_KEY="macd-stoch-v2-3-hybrid-v1"
MIN_MICRO_BARS=4
MAX_1M_AGE_SECONDS=95
MAX_MICRO_AGE_SECONDS=6
MAX_QUOTE_FETCH=275
MICRO_WINDOW_MINUTES=4


def utc(value):
    t=value if isinstance(value,datetime) else datetime.fromisoformat(
        str(value).replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return t.astimezone(timezone.utc)


def _envelope(*,stamp,amount,action,reason,new=False):
    return ClosedBarDecisionV3(
        f"hybrid15:{stamp}:{action}",
        MacdHistogramDecisionV3(
            TargetInventoryV3(round(float(amount),10)),action,reason,0.,
        ),
        new,
    )


def macro_direction_from_closed_1m(bars,observations,*,now):
    """Return 1/-1 only for two strong aligned CLOSED V2.1 composites."""
    clock=utc(now)
    if len(bars)<40 or len(observations)<2:
        return 0,"NO_MACRO_HISTORY"
    latest_bar=utc(bars[-1].bar_time)
    if (latest_bar-utc(bars[-2].bar_time)).total_seconds()!=60:
        return 0,"GAPPED_MACRO"
    if not 0 <= (clock-latest_bar-timedelta(minutes=1)).total_seconds() <= MAX_1M_AGE_SECONDS:
        return 0,"STALE_MACRO"
    now_score=composite_score_v3(observations[-1],bars)
    prev_score=composite_score_v3(observations[-2],bars[:-1])
    if now_score is None or prev_score is None:
        return 0,"NO_COMPOSITE"
    current=float(now_score[0])
    earlier=float(prev_score[0])
    if abs(current)<=EXIT_THRESHOLD:
        return 0,"MACRO_WEAK_FLAT"
    if (abs(current)<ENTRY_THRESHOLD or abs(earlier)<ENTRY_THRESHOLD
            or current*earlier<=0):
        return 0,"MACRO_UNCONFIRMED"
    return (1 if current>0 else -1),f"MACRO_ALIGNED_{current:+.3f}_{earlier:+.3f}"


def micro_target_from_completed_bbo(*,bars,macro_side,current_amount,
                                    tranche,max_amount,now,latest_spread_bps=0.):
    """Never reverse based solely on 15s noise; 1m macro owns direction."""
    clock=utc(now)
    actual=float(current_amount)
    if not isfinite(tranche) or tranche<=0 or max_amount<tranche:
        raise ValueError("invalid legal Saxo tranche/max inventory")
    if not macro_side:
        return 0.,"MACRO_FLAT"
    if actual*macro_side<0:
        return 0.,"MACRO_OPPOSITE_FLAT"
    if len(bars)<MIN_MICRO_BARS:
        return actual if actual*macro_side>0 else 0.,"NO_MICRO_HISTORY"
    curr=bars[-1]
    end=utc(curr.bar_time)+timedelta(seconds=15)
    if not 0<=(clock-end).total_seconds()<=MAX_MICRO_AGE_SECONDS:
        return actual if actual*macro_side>0 else 0.,"STALE_MICRO"
    seq=(bars[-3],bars[-2],bars[-1])
    for a,b in zip(seq,seq[1:]):
        if (utc(b.bar_time)-utc(a.bar_time)).total_seconds()!=15:
            return actual if actual*macro_side>0 else 0.,"MICRO_GAP"
    prices=[float(x.close) for x in seq]
    b1,b2=seq[-2:]
    # Two independently CLOSED in-direction candles: no 1-candle chasing.
    green=all(macro_side*(float(x.close)-float(x.open))>0 for x in (b1,b2))
    advancing=macro_side*(prices[-1]-prices[-2])>0
    # Require a non-trivial price move compared with spread: avoids
    # entering where a 15s move barely pays the bid/ask crossing.
    micro_bp=10000*abs(prices[-1]-prices[-2])/prices[-2]
    enough_move=micro_bp>=max(1.5,1.20*latest_spread_bps)
    # Strong adverse micro reversal: two bars, not a single red wick.
    adverse=all(macro_side*(float(x.close)-float(x.open))<0 for x in (b1,b2))
    reversing=macro_side*(prices[-1]-prices[-3])<0
    if actual*macro_side>0 and adverse and reversing and enough_move:
        return 0.,"MICRO_ADVERSE_FLAT"
    if green and advancing and enough_move:
        if abs(actual)<tranche/2:
            return macro_side*tranche,"MICRO_ENTRY_2X15S"
        # Builders must see fresh 15s confirmation; size is constrained by
        # exact legal Saxo instrument + broker's capacity gate.
        amount=min(max_amount,abs(actual)+tranche)
        return round(macro_side*amount,10),"MICRO_BUILD_2X15S"
    return actual if actual*macro_side>0 else 0.,"MICRO_WAIT"


def _ensure_hybrid_state(db):
    db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_hybrid_15s_state (
      trader_id TEXT PRIMARY KEY,context TEXT NOT NULL,
      last_15s_end TEXT,desired_amount DOUBLE PRECISION NOT NULL,
      last_action TEXT NOT NULL,updated_at TEXT NOT NULL
    )""")


def evaluate_hybrid_live_v3(*,trader_id,strategy_key,account_uic,instrument_id,
                            market_name,actual_amount,tranche,max_inventory,
                            context_changed=False,db_path="pricegauger.db",now=None):
    if strategy_key!=RUNTIME_KEY:
        raise ValueError("unsupported hybrid strategy")
    clock=utc(now or datetime.now(timezone.utc))
    actual=float(actual_amount)
    context=f"{strategy_key}|{int(account_uic)}|{int(instrument_id)}"
    def hold(why,stamp="no-quote"):
        return _envelope(
            stamp=f"{trader_id}:{stamp}",amount=actual,
            action="HOLD_"+why,reason="V2.3 "+why+"; no new exposure",
        )
    # Do not send fresh entry signals from a strategy switch; retain exact
    # inventory until a new fully-closed 15s decision arrives.
    with connect(db_path) as db:
        _ensure_hybrid_state(db)
        row=db.execute("""SELECT context,last_15s_end,desired_amount FROM
          autotrader_v3_hybrid_15s_state WHERE trader_id=?""",(trader_id,)).fetchone()
    if context_changed or (row and str(row["context"])!=context):
        with connect(db_path) as db:
            _ensure_hybrid_state(db)
            db.execute("""INSERT INTO autotrader_v3_hybrid_15s_state(
                trader_id,context,last_15s_end,desired_amount,last_action,updated_at)
              VALUES(?,?,NULL,?,'CONTEXT_RESET',?)
              ON CONFLICT(trader_id) DO UPDATE SET
              context=excluded.context,last_15s_end=NULL,
              desired_amount=excluded.desired_amount,
              last_action=excluded.last_action,updated_at=excluded.updated_at""",
              (trader_id,context,actual,clock.isoformat()))
        return hold("CONTEXT_RESET")
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT quote_at,received_at,bid,ask
                FROM lsim_hyper_quotes_1s
                WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
                ORDER BY quote_at LIMIT ?""",(
                int(account_uic),
                (clock-timedelta(minutes=MICRO_WINDOW_MINUTES)).isoformat(),
                clock.isoformat(),MAX_QUOTE_FETCH+1)).fetchall()
        if len(rows)>MAX_QUOTE_FETCH:
            return hold("QUOTE_LIMIT")
        quotes=validate_quotes_v1(tuple(dict(x) for x in rows))
        if not quotes or (clock-quotes[-1].at).total_seconds()>MAX_MICRO_AGE_SECONDS:
            return hold("STALE_QUOTES")
        bars15=build_completed_bars_v1(
            quotes,interval_seconds=15,market=market_name,
            observed_through=clock,
        )
        if len(bars15)<MIN_MICRO_BARS:
            return hold("INCOMPLETE_15S")
        closed_stamp=bars15[-1].closed_at
        if (clock-closed_stamp).total_seconds()>MAX_MICRO_AGE_SECONDS:
            return hold("STALE_15S")
        if row and row["last_15s_end"] and utc(row["last_15s_end"])>=closed_stamp:
            return hold("DUPLICATE_15S",closed_stamp.isoformat())
        # The native 1m source is an independent, confirmed-bar feed.
        raw=CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=int(instrument_id),
            start=clock-timedelta(hours=5),end=clock,limit=350)
        closed=closed_bars_v2(
            tuple(x.point for x in raw),market=market_name,
            timeframe_minutes=1) if raw else ()
        obs=macd_observations_v2(closed,timeframe_minutes=1) if closed else ()
        direction,reason=macro_direction_from_closed_1m(
            closed,obs,now=clock)
        spread=quotes[-1].ask-quotes[-1].bid
        spread_bps=10000*spread/quotes[-1].mid
        amount,action=micro_target_from_completed_bbo(
            bars=tuple(x.bar for x in bars15),
            macro_side=direction,current_amount=actual,
            tranche=tranche,max_amount=max_inventory,
            now=clock,latest_spread_bps=spread_bps,
        )
        # Macro-invalid data must NOT grant a new order; a validated
        # macro FLAT can still request exit through ordinary broker guards.
        if not direction and reason in (
            "NO_MACRO_HISTORY","STALE_MACRO","NO_COMPOSITE",
        ):
            amount=actual
            action="NO_FRESH_1M"
        with connect(db_path) as db:
            _ensure_hybrid_state(db)
            db.execute("""INSERT INTO autotrader_v3_hybrid_15s_state(
              trader_id,context,last_15s_end,desired_amount,last_action,updated_at)
              VALUES(?,?,?,?,?,?)
              ON CONFLICT(trader_id) DO UPDATE SET
              context=excluded.context,last_15s_end=excluded.last_15s_end,
              desired_amount=excluded.desired_amount,last_action=excluded.last_action,
              updated_at=excluded.updated_at""",(
              trader_id,context,closed_stamp.isoformat(),float(amount),
              action,clock.isoformat()))
        return _envelope(
            stamp=f"{trader_id}:{closed_stamp.isoformat()}",
            amount=amount,action=action,new=True,
            reason=(f"V2.3 hybrid: {reason}; {action}; "
                    f"macro 1m, micro 15s closed; observed spread={spread_bps:.2f} bp. "
                    "V3 guarded Saxo execution and reconciliation mandatory"),
        )
    except (ValueError,TypeError,KeyError,OverflowError):
        return hold("BAD_BBO_OR_MACRO")
    except Exception:
        # No speculative entry when a quote/database indicator source fails.
        return hold("SOURCE_UNAVAILABLE")


def evaluate_hybrid_compat_v3(*,trader_id,observation,actual_inventory=0.,**kwargs):
    """Generic strategy registry probe: no synthetic minute-order authority."""
    del trader_id,observation,kwargs
    return _envelope(stamp="compat",amount=actual_inventory or 0.,
                     action="WAIT_15S_BBO",
                     reason="V2.3 requires closed 1m plus genuine Saxo 15s BBO")


__all__=["CATALOG_KEY","RUNTIME_KEY","macro_direction_from_closed_1m",
         "micro_target_from_completed_bbo","evaluate_hybrid_live_v3",
         "evaluate_hybrid_compat_v3"]
