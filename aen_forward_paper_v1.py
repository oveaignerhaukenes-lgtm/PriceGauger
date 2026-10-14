"""AEn: bounded, durable FORWARD PAPER evidence, completely separate from Saxo.

Enrolment happens at the NEXT minute boundary. No earlier return is persisted.
The worker consumes only already-completed canonical bars. It never trades.
Historical recomputation is used to audit each prospective point; committed
observations are append-only and a data revision suspends the cohort, instead
of silently rewriting its forward result.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from math import isfinite

from database import connect
from aen_replay_v1 import (
    AEnPaperConfig, ENGINE_VERSION, FAMILIES, replay, prepare_replay_inputs, utc,
)

LOGGER = logging.getLogger("pricegauger.aen.forward")
FORWARD_VERSION = "aen-forward-v2-frozen-input"
LIFETIME_DAYS = 14
LOOKBACK_DAYS = 3
MAX_COHORTS = 5
SAMPLE_MINUTES = 5

# Frozen comparisons start with the minimal 1-unit risk budget, not the
# optimistic 5-unit historical presets.
FROZEN_PRESETS = (
    AEnPaperConfig(family="MACD Hold",minutes=5,structure_minutes=5,max_units=1),
    AEnPaperConfig(family="MACD Histogram",minutes=5,structure_minutes=5,max_units=1),
    AEnPaperConfig(family="MACD Hysteresis",minutes=5,structure_minutes=5,max_units=1),
    AEnPaperConfig(family="MACD + Stochastic",minutes=5,structure_minutes=5,max_units=1),
    AEnPaperConfig(family="MACD Hold",minutes=10,structure_minutes=5,max_units=1,
                   adaptive=True,dwell_minutes=20),
)


def ensure_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS aen_forward_runs (
            run_id TEXT PRIMARY KEY,
            instrument_id INTEGER NOT NULL,
            market_name TEXT NOT NULL,
            engine_version TEXT NOT NULL,
            config_json TEXT NOT NULL,
            enrolled_at TEXT NOT NULL,
            status TEXT NOT NULL,
            last_bar_end TEXT,
            prefix_sha TEXT,
            net_pct REAL NOT NULL DEFAULT 0,
            gross_pct REAL NOT NULL DEFAULT 0,
            max_dd_pct REAL NOT NULL DEFAULT 0,
            units INTEGER NOT NULL DEFAULT 0,
            executions INTEGER NOT NULL DEFAULT 0,
            turnover_units INTEGER NOT NULL DEFAULT 0,
            cost_pct REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS aen_forward_runs_status
          ON aen_forward_runs(status, instrument_id);
        -- Reproducible AS-SEEN evidence: later upstream OHLCV corrections
        -- never rewrite what the PAPER simulator actually consumed.
        CREATE TABLE IF NOT EXISTS aen_forward_frozen_bars (
            series_version TEXT NOT NULL,
            instrument_id INTEGER NOT NULL,
            bar_time TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL,
            PRIMARY KEY (series_version,instrument_id,bar_time)
        );
        CREATE TABLE IF NOT EXISTS aen_forward_points (
            run_id TEXT NOT NULL,
            bar_end TEXT NOT NULL,
            net_pct REAL NOT NULL,
            gross_pct REAL NOT NULL,
            units INTEGER NOT NULL,
            executions INTEGER NOT NULL,
            PRIMARY KEY(run_id, bar_end)
        );
        """)


def _run_id(instrument_id, cfg):
    payload = json.dumps([FORWARD_VERSION, ENGINE_VERSION, instrument_id,
                          asdict(cfg)],sort_keys=True,separators=(",",":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _eligible(db):
    """Use an actual, already-subscribed LAB feed; no account or Saxo mapping."""
    try:
        # Psycopg parses literal '%' in query text as parameter syntax, even
        # when the statement has no qmark values. Perform a small bounded
        # lookup and filter names in Python instead of SQL LIKE wildcards.
        rows = db.execute("""
            SELECT instrument_id,market_name FROM lsim_feature_cursors
            ORDER BY instrument_id LIMIT 50
        """).fetchall()
    except Exception:
        # No LAB feed/schema yet: do not create a speculative paper market.
        return []
    return [(int(x["instrument_id"]),str(x["market_name"])) for x in rows
            if ("TECH" in str(x["market_name"]).upper() or
                "NAS" in str(x["market_name"]).upper())][:1]


def _seed(db, instrument_id, market, now):
    # Deterministic immutable enrolment; old runs never get reset at deploy.
    enrolled = (utc(now).replace(second=0,microsecond=0)
                + timedelta(minutes=1)).isoformat()
    for cfg in FROZEN_PRESETS[:MAX_COHORTS]:
        cursor=db.execute("""
            INSERT INTO aen_forward_runs(
                run_id,instrument_id,market_name,engine_version,config_json,
                enrolled_at,status)
            VALUES(?,?,?,?,?,?,'ACTIVE')
            ON CONFLICT(run_id) DO NOTHING
        """,(_run_id(instrument_id,cfg),instrument_id,market,
             ENGINE_VERSION,json.dumps(asdict(cfg),sort_keys=True),
             enrolled))
        if cursor.rowcount:
            LOGGER.info("AEn forward enrolled market=%s run=%s tf=%dm",
                        market,_run_id(instrument_id,cfg)[:8],cfg.minutes)


def _capture_new_bars(db,instrument_id,enrolled,now):
    """Snapshot exactly what was observable at this run, never revise old rows.

    Historical warmup is captured only once. Later cycles append NEW completed
    market bars, not updates to previously seen bars. This makes PAPER data
    causal/as-seen even when the canonical ingestion feed is later corrected.
    One Tech100 series is bounded to the 14-day experiment + 3-day warmup.
    """
    previous=db.execute("""
        SELECT MAX(bar_time) AS t FROM aen_forward_frozen_bars
        WHERE series_version=? AND instrument_id=?
    """,(FORWARD_VERSION,instrument_id)).fetchone()
    lower=(utc(previous["t"])+timedelta(minutes=1) if previous and previous["t"]
           else utc(enrolled)-timedelta(days=LOOKBACK_DAYS)).isoformat()
    cutoff=(utc(now)-timedelta(minutes=1,seconds=5)).isoformat()
    if lower>cutoff:
        return 0
    # Bounded read: at most 3 days initial warmup, then ~1 new bar/cycle.
    rows=db.execute("""
        SELECT b.bar_time,b.open,b.high,b.low,b.close,b.volume
        FROM pg_v2_market_bars_1m b
        WHERE b.instrument_id=? AND b.bar_time>=? AND b.bar_time<=?
        ORDER BY b.bar_time ASC LIMIT 25000
    """,(instrument_id,lower,cutoff)).fetchall()
    copied=0
    for row in rows:
        price=(float(row["open"]),float(row["high"]),
               float(row["low"]),float(row["close"]))
        if not all(isfinite(x) for x in price):
            continue
        if price[2]<=0 or not price[2]<=price[3]<=price[1]:
            continue
        # Normalize timestamps across PG TIMESTAMPTZ / SQLite TEXT to
        # stable UTC text. ON CONFLICT DO NOTHING is deliberate evidence policy.
        volume=None if row["volume"] is None else float(row["volume"])
        if volume is not None and (not isfinite(volume) or volume < 0):
            volume=None
        cursor=db.execute("""
            INSERT INTO aen_forward_frozen_bars(
                series_version,instrument_id,bar_time,open,high,low,close,volume)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(series_version,instrument_id,bar_time) DO NOTHING
        """,(FORWARD_VERSION,instrument_id,utc(row["bar_time"]).isoformat(),
             *price,volume))
        copied+=max(0,int(cursor.rowcount or 0))
    return copied


def _load_closed(db,instrument_id,enrolled,now):
    """Load frozen-as-seen OHLCV, not today's corrected source history."""
    lower=(utc(enrolled)-timedelta(days=LOOKBACK_DAYS)).isoformat()
    cutoff=(utc(now)-timedelta(minutes=1,seconds=5)).isoformat()
    return db.execute("""
        SELECT b.bar_time,b.open,b.high,b.low,b.close,b.volume
        FROM aen_forward_frozen_bars b
        WHERE b.series_version=? AND b.instrument_id=?
          AND b.bar_time>=? AND b.bar_time<=?
        ORDER BY b.bar_time ASC LIMIT 25000
    """,(FORWARD_VERSION,instrument_id,lower,cutoff)).fetchall()


class _Bar:
    """Minimal broker-free shape consumed by canonical replay."""
    def __init__(self,row,market):
        self.bar_time = utc(row["bar_time"]).isoformat()
        self.market_name = market
        self.open = float(row["open"])
        self.high = float(row["high"])
        self.low = float(row["low"])
        self.close = float(row["close"])
        self.volume = None if row["volume"] is None else float(row["volume"])


def _input_digest(rows, upto):
    """Bar-by-bar immutable prefix, including zero-position warmup context."""
    sha=hashlib.sha256()
    for r in rows:
        if utc(r["bar_time"])+timedelta(minutes=1)>utc(upto):
            break
        record=(utc(r["bar_time"]).isoformat(),float(r["open"]),
                float(r["high"]),float(r["low"]),float(r["close"]),
                None if r["volume"] is None else float(r["volume"]))
        sha.update(json.dumps(record,separators=(",",":"),allow_nan=False).encode())
        sha.update(b"\n")
    return sha.hexdigest()


def _settle_group(db,runs,now):
    instrument_id=int(runs[0]["instrument_id"])
    enrolled=min(utc(row["enrolled_at"]) for row in runs)
    # No need to reread and replay on cycles with zero new closed 1m bars.
    cutoff=(utc(now)-timedelta(minutes=1,seconds=5)).isoformat()
    latest=db.execute("""
        SELECT MAX(bar_time) AS t FROM aen_forward_frozen_bars
        WHERE series_version=? AND instrument_id=? AND bar_time<=?
    """,(FORWARD_VERSION,instrument_id,cutoff)).fetchone()
    if not latest or not latest["t"]:
        return 0
    latest_closed=utc(latest["t"])+timedelta(minutes=1)
    if latest_closed <= enrolled:
        return 0
    if all(row["last_bar_end"] is not None and
           latest_closed <= utc(row["last_bar_end"]) for row in runs):
        return 0
    raw=_load_closed(db,instrument_id,enrolled,now)
    if not raw:
        return 0
    bars=tuple(_Bar(row,str(runs[0]["market_name"])) for row in raw)
    # All published cohorts share structure resolution; compute indicators ONCE.
    first=AEnPaperConfig(**json.loads(runs[0]["config_json"]))
    prepared=prepare_replay_inputs(bars,first)
    settled=0
    for row in runs:
        run_id=str(row["run_id"])
        cfg=AEnPaperConfig(**json.loads(row["config_json"]))
        started=utc(row["enrolled_at"])
        if row["engine_version"]!=ENGINE_VERSION:
            db.execute("UPDATE aen_forward_runs SET status='PAUSED_VERSION' WHERE run_id=?",
                       (run_id,))
            continue
        if utc(now)-started > timedelta(days=LIFETIME_DAYS):
            db.execute("UPDATE aen_forward_runs SET status='COMPLETED' WHERE run_id=?",
                       (run_id,))
            continue
        # Never reject the cohort merely for short pre-enrolment history.
        # 12/26/9 MACD and swing pivots warm up causally; until then replay
        # stays FLAT. Enrolment and observations still begin prospectively.
        report=replay(cfg,bars,started_at=started,prepared=prepared)
        if not report.points:
            continue
        last_end=utc(report.points[-1][0])
        if last_end <= started or (row["last_bar_end"] and
                                 last_end<=utc(row["last_bar_end"])):
            continue
        points_by_end={utc(x[0]):x for x in report.points}
        if row["last_bar_end"]:
            cursor=utc(row["last_bar_end"])
            revision=(bool(row["prefix_sha"]) and
                      _input_digest(raw,cursor)!=row["prefix_sha"])
            previous=points_by_end.get(cursor)
            # Even a tiny mismatch means historical data/rules changed:
            # fail closed rather than silently restating forward returns.
            if revision or previous is None or abs(float(previous[1])-float(row["net_pct"]))>1e-7:
                db.execute("""
                    UPDATE aen_forward_runs SET status='PAUSED_REVISION',
                    updated_at=CURRENT_TIMESTAMP WHERE run_id=?
                """,(run_id,))
                LOGGER.warning(
                    "AEn forward replay divergence run=%s input_changed=%s "
                    "pnl_changed=%s prior_pct=%.8f recomputed_pct=%s",
                    run_id,revision,
                    previous is None or abs(float(previous[1])-float(row["net_pct"]))>1e-7,
                    float(row["net_pct"]),
                    "MISSING" if previous is None else "%.8f"%float(previous[1]))
                continue
        cursor=utc(row["last_bar_end"]) if row["last_bar_end"] else started
        fill_close_times={utc(fill[0])+timedelta(minutes=1) for fill in report.fills}
        for at,(stamp,net,gross,units) in points_by_end.items():
            if at<=cursor:
                continue
            if int(at.timestamp()//60)%SAMPLE_MINUTES!=0 and at not in fill_close_times:
                continue
            # The last known execution count at each sampled point, not the
            # final replay total, is recorded for correct temporal attribution.
            executions=sum(utc(f[0])+timedelta(minutes=1)<=at for f in report.fills)
            db.execute("""
                INSERT INTO aen_forward_points(
                    run_id,bar_end,net_pct,gross_pct,units,executions)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(run_id,bar_end) DO NOTHING
            """,(run_id,stamp,float(net),float(gross),int(units),executions))
        db.execute("""
            UPDATE aen_forward_runs
            SET last_bar_end=?,prefix_sha=?,net_pct=?,gross_pct=?,max_dd_pct=?,
                units=?,executions=?,turnover_units=?,cost_pct=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE run_id=? AND status='ACTIVE'
        """,(report.points[-1][0],_input_digest(raw,last_end),float(report.return_pct),float(report.gross_pct),
             float(report.max_drawdown_pct),int(report.points[-1][3]),
             int(report.executions),int(report.turnover_units),
             float(report.total_cost_pct),run_id))
        settled+=1
    return settled


def process_forward_cycle(*,db_path="pricegauger.db",now=None):
    """Append immutable future evidence only; idempotent across restarts."""
    moment=utc(now or datetime.now(timezone.utc))
    ensure_schema(db_path)
    total=0
    with connect(db_path) as db:
        for instrument_id,market in _eligible(db):
            _seed(db,instrument_id,market,moment)
            # Expiration is an independent, wall-clock event. A flat/stale
            # feed must not keep a 14-day cohort ACTIVE forever.
            expiry=(moment-timedelta(days=LIFETIME_DAYS)).isoformat()
            db.execute("""
                UPDATE aen_forward_runs SET status='COMPLETED'
                WHERE instrument_id=? AND status='ACTIVE'
                  AND enrolled_at<?
            """,(instrument_id,expiry))
            # A previous build could pause brand-new runs for insufficient
            # prehistory. They contain no observed points or inventory.
            # They may safely resume at their ORIGINAL prospective start.
            db.execute("""
                UPDATE aen_forward_runs SET status='ACTIVE'
                WHERE instrument_id=? AND status='PAUSED_HISTORY'
                  AND last_bar_end IS NULL
            """,(instrument_id,))
            rows=db.execute("""
                SELECT * FROM aen_forward_runs
                WHERE instrument_id=? AND status='ACTIVE'
                ORDER BY run_id LIMIT ?
            """,(instrument_id,MAX_COHORTS)).fetchall()
            if rows:
                enrolled=min(utc(row["enrolled_at"]) for row in rows)
                captured=_capture_new_bars(db,instrument_id,enrolled,moment)
                if captured:
                    LOGGER.info("AEn forward immutable input captured=%d market=%s",
                                captured,market)
                total+=_settle_group(db,rows,moment)
                latest=max((str(row["last_bar_end"]) for row in rows
                            if row["last_bar_end"]),default="WAITING")
                LOGGER.info("AEn forward heartbeat market=%s active=%d last_bar=%s settled=%d",
                            market,len(rows),latest,total)
            else:
                summary=db.execute("""
                    SELECT status,COUNT(*) AS n FROM aen_forward_runs
                    WHERE instrument_id=? GROUP BY status
                """,(instrument_id,)).fetchall()
                LOGGER.info("AEn forward no-active market=%s statuses=%s",
                            market,[(x["status"],x["n"]) for x in summary])
    return total


def forward_snapshot(*,db_path="pricegauger.db",instrument_id=None,limit=1500):
    """Read-only UI query: reporting does not seed, reset or change any run."""
    with connect(db_path) as db:
        selector="WHERE instrument_id=?" if instrument_id is not None else ""
        params=(int(instrument_id),) if instrument_id is not None else ()
        runs=db.execute(f"""
            SELECT * FROM aen_forward_runs {selector}
            ORDER BY enrolled_at DESC,run_id LIMIT 50
        """,params).fetchall()
        ids=[str(row["run_id"]) for row in runs]
        points=[]
        for run_id in ids:
            found=db.execute("""
                SELECT run_id,bar_end,net_pct,gross_pct,units,executions
                FROM aen_forward_points WHERE run_id=?
                ORDER BY bar_end DESC LIMIT ?
            """,(run_id,max(1,min(2500,int(limit))))).fetchall()
            points.extend(dict(row) for row in found)
        return [dict(row) for row in runs],points


def forward_health_snapshot(*, db_path="pricegauger.db"):
    """Read-only bounded liveness evidence without user/account or strategy secrets.

    The existing SIM worker calls this after process_forward_cycle; the health
    reader neither seeds cohorts nor mutates the database.
    """
    with connect(db_path) as db:
        feeds=_eligible(db)
        states=db.execute("""
            SELECT instrument_id,status,COUNT(*) AS n,
                   MAX(last_bar_end) AS last_bar,
                   MIN(enrolled_at) AS first_enrol
            FROM aen_forward_runs
            GROUP BY instrument_id,status
            ORDER BY instrument_id,status LIMIT 20
        """).fetchall()
        return {
            "feeds":len(feeds),
            "markets":[market for _,market in feeds],
            "cohorts":[{
                "instrument_id":int(row["instrument_id"]),
                "status":str(row["status"]),
                "count":int(row["n"]),
                "last_bar":row["last_bar"],
                "first_enrol":row["first_enrol"],
            } for row in states],
        }
