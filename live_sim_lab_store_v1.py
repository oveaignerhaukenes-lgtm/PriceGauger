"""Durable forward-only Live-Sim Lab runtime and independent experiment ledger.

Lab has no Saxo imports, no account credentials, and no execution authority.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timedelta, timezone

from database import connect
from live_sim_lab_core_v1 import advance_features, initial_features, settle_bar, utc

MAX_ACTIVE_LAB_VARIANTS = 100
ENGINE_VERSION = "live-sim-lab-v1"


def ensure_lab_schema(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_feature_cursors(
          instrument_id INTEGER PRIMARY KEY, market_name TEXT NOT NULL,
          last_bar_time TEXT NOT NULL, state_json TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lsim_experiments(
          experiment_id TEXT PRIMARY KEY, instrument_id INTEGER NOT NULL,
          market_name TEXT NOT NULL, family TEXT NOT NULL, signal_tf INTEGER NOT NULL,
          regime_tf INTEGER NOT NULL, modifier TEXT NOT NULL, max_exposure REAL NOT NULL,
          cost_bps REAL NOT NULL, config_json TEXT NOT NULL, engine_version TEXT NOT NULL,
          started_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE'
        );
        CREATE INDEX IF NOT EXISTS lsim_active_instrument
          ON lsim_experiments(instrument_id,status);
        CREATE TABLE IF NOT EXISTS lsim_states(
          experiment_id TEXT PRIMARY KEY, state_json TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS lsim_points(
          experiment_id TEXT NOT NULL, bar_time TEXT NOT NULL,
          equity REAL NOT NULL, exposure REAL NOT NULL, regime TEXT NOT NULL,
          decision TEXT NOT NULL, traded INTEGER NOT NULL,
          PRIMARY KEY(experiment_id,bar_time)
        );
        CREATE TABLE IF NOT EXISTS lsim_regime_memory(
          experiment_id TEXT NOT NULL, regime TEXT NOT NULL,
          observed_bars INTEGER NOT NULL, sum_delta_nav REAL NOT NULL,
          PRIMARY KEY(experiment_id,regime)
        );
        CREATE TABLE IF NOT EXISTS lsim_daily_reports(
          report_date TEXT PRIMARY KEY, created_at TEXT NOT NULL,
          data_json TEXT NOT NULL
        );
        """)


def candidate_configs():
    """72 locked configurations, leaving 28 of the 100 slots for later variants."""
    for family, signal_tf, regime_tf, modifier, exposure in itertools.product(
        ("sticky", "fast_exit"), (2, 5), (10, 15, 30),
        ("none", "whipsaw_pause", "impulse_exit"), (0.5, 1.0),
    ):
        yield {"family": family, "signal_tf": signal_tf, "regime_tf": regime_tf,
               "modifier": modifier, "max_exposure": exposure, "cost_bps": 5.0}


def _new_experiment_id(instrument_id, cfg):
    payload = json.dumps([ENGINE_VERSION, instrument_id, cfg], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def seed_default_experiments(db, *, instrument_id, market_name, now):
    """Insert immutable, prospective variants only; never backdate their trades."""
    count = db.execute(
        "SELECT COUNT(*) AS n FROM lsim_experiments WHERE status='ACTIVE'"
    ).fetchone()["n"]
    created = 0
    for cfg in candidate_configs():
        key = _new_experiment_id(instrument_id, cfg)
        exists = db.execute(
            "SELECT 1 FROM lsim_experiments WHERE experiment_id=?", (key,)
        ).fetchone()
        if exists:
            continue
        if count >= MAX_ACTIVE_LAB_VARIANTS:
            break
        db.execute("""
            INSERT INTO lsim_experiments(
              experiment_id,instrument_id,market_name,family,signal_tf,regime_tf,
              modifier,max_exposure,cost_bps,config_json,engine_version,started_at,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (key, instrument_id, market_name, cfg["family"], cfg["signal_tf"],
              cfg["regime_tf"], cfg["modifier"], cfg["max_exposure"], cfg["cost_bps"],
              json.dumps(cfg, sort_keys=True), ENGINE_VERSION, now, "ACTIVE"))
        count += 1
        created += 1
    return created


def _eligible_instruments(db):
    """One exact subscribed Tech100 instrument; never mix provider identities."""
    rows = db.execute("""
        SELECT DISTINCT b.instrument_id, m.name AS market_name
        FROM pg_v2_market_bars_1m b
        JOIN pg_v2_instruments i ON i.instrument_id=b.instrument_id AND i.active=TRUE
        JOIN pg_v2_markets m ON m.market_id=i.market_id AND m.active=TRUE
        JOIN pg_v2_collection_subscriptions c ON c.instrument_id=i.instrument_id AND c.enabled=TRUE
        ORDER BY b.instrument_id
    """).fetchall()
    return [(int(r["instrument_id"]), str(r["market_name"])) for r in rows
            if "TECH" in str(r["market_name"]).upper() or "NAS" in str(r["market_name"]).upper()][:1]


def _load_bars(db, instrument_id, cursor, cutoff, limit=1000):
    where = "AND bar_time>?" if cursor is not None else ""
    params = [instrument_id]
    if cursor is not None:
        params.append(cursor)
    params.extend([cutoff, limit])
    rows = db.execute(
        "SELECT bar_time,open,high,low,close FROM pg_v2_market_bars_1m "
        "WHERE instrument_id=? " + where + " AND bar_time<=? "
        "ORDER BY bar_time ASC LIMIT ?", params
    ).fetchall()
    return rows


def _bootstrap_features(db, instrument_id, market_name, cutoff):
    # Warm up from the most recent *already closed* bars; never backtest equity.
    rows = db.execute("""
        SELECT bar_time,close FROM pg_v2_market_bars_1m
        WHERE instrument_id=? AND bar_time<=?
        ORDER BY bar_time DESC LIMIT 1100
    """, (instrument_id, cutoff)).fetchall()
    if not rows:
        return None
    features = initial_features()
    for bar in reversed(rows):
        features = advance_features(features, bar_time=bar["bar_time"], close=bar["close"])
    db.execute("""
        INSERT INTO lsim_feature_cursors(instrument_id,market_name,last_bar_time,state_json)
        VALUES(?,?,?,?)
    """, (instrument_id, market_name, features["last_bar"], json.dumps(features)))
    return features


def process_lab_cycle(*, db_path="pricegauger.db", now=None):
    """Evaluate only newly closed 1m bars once, shared across up to 100 variants.

    Cursor, paper ledgers and causal regime-memory commits are one transaction.
    Missing bars are replayed in order from the last committed cursor, without
    resetting P&L or recalculating indicator history.
    """
    ensure_lab_schema(db_path)
    moment = utc(now or datetime.now(timezone.utc))
    # A 1m candle with open timestamp t must have ended before we consume it.
    cutoff = (moment - timedelta(minutes=1, seconds=5)).isoformat()
    now_stamp = moment.isoformat()
    processed = 0
    from live_sim_lab_evolution_v1 import (
        ensure_evolution_schema, load_shadow_states, settle_shadow,
        update_observation, persist_shadow_states, seed_trial_ledger,
        run_evolution_maintenance,
    )
    from live_sim_lab_context_ablation_v1 import (
        ensure_context_lab_schema,settle_context_ablations,
    )
    with connect(db_path) as db:
        ensure_evolution_schema(db)
        ensure_context_lab_schema(db)
        for instrument_id, market in _eligible_instruments(db):
            row = db.execute("SELECT state_json FROM lsim_feature_cursors WHERE instrument_id=?",
                             (instrument_id,)).fetchone()
            if row is None:
                features = _bootstrap_features(db, instrument_id, market, cutoff)
                if features is None:
                    continue
                seed_default_experiments(db, instrument_id=instrument_id,
                                         market_name=market, now=now_stamp)
                seed_trial_ledger(db,instrument_id=instrument_id,now=now_stamp)
                continue
            features = json.loads(row["state_json"])
            experiments = db.execute("""
                SELECT experiment_id,config_json,started_at
                FROM lsim_experiments WHERE instrument_id=? AND status='ACTIVE'
                ORDER BY experiment_id
            """, (instrument_id,)).fetchall()
            # This global check applies even if new experiments were added out-of-band.
            if len(experiments) > MAX_ACTIVE_LAB_VARIANTS:
                raise ValueError("Active Live-Sim Lab variant count exceeds 100")
            states = {}
            for exp in experiments:
                s = db.execute("SELECT state_json FROM lsim_states WHERE experiment_id=?",
                               (exp["experiment_id"],)).fetchone()
                states[exp["experiment_id"]] = json.loads(s["state_json"]) if s else {}
            shadows = load_shadow_states(db, instrument_id)
            bars = _load_bars(db, instrument_id, features["last_bar"], cutoff)
            for bar in bars:
                bar_at = utc(bar["bar_time"]).isoformat()
                prior_regime = features["regime"]
                features = advance_features(features, bar_time=bar_at, close=bar["close"])
                processed += 1
                for exp in experiments:
                    if bar_at < utc(exp["started_at"]).isoformat():
                        continue
                    key = exp["experiment_id"]
                    cfg = json.loads(exp["config_json"])
                    before_state = states[key]
                    state, result = settle_bar(
                        cfg, states[key], features, bar_time=bar_at,
                        open_price=bar["open"], close_price=bar["close"])
                    states[key] = update_observation(
                        state,before_state,prior_regime=prior_regime,bar_time=bar_at)
                    if result["trade"] or (int(utc(bar_at).timestamp()) // 60) % 5 == 0:
                        db.execute("""
                            INSERT INTO lsim_points(
                              experiment_id,bar_time,equity,exposure,regime,decision,traded)
                            VALUES(?,?,?,?,?,?,?)
                            ON CONFLICT(experiment_id,bar_time) DO NOTHING
                        """, (key, bar_at, result["equity"], result["exposure"],
                              prior_regime, result["decision"], int(result["trade"])))
                    # Attribution uses PREVIOUS regime, classified before this bar's return.
                    db.execute("""
                        INSERT INTO lsim_regime_memory(
                          experiment_id,regime,observed_bars,sum_delta_nav)
                        VALUES(?,?,1,?)
                        ON CONFLICT(experiment_id,regime) DO UPDATE SET
                          observed_bars=lsim_regime_memory.observed_bars+1,
                          sum_delta_nav=lsim_regime_memory.sum_delta_nav+excluded.sum_delta_nav
                    """, (key, prior_regime, result["delta_equity"]))
                # Selector observes today's settled candidate evidence only after
                # the candle closes. Chosen exposure is filled at NEXT open.
                available = {e["experiment_id"]:states[e["experiment_id"]]
                             for e in experiments if states.get(e["experiment_id"])}
                settle_shadow(
                    db,instrument_id=instrument_id,states=shadows,candidates=available,
                    features=features,prior_regime=prior_regime,bar_time=bar_at,
                    open_price=bar["open"],close_price=bar["close"])
                # Independently score five frozen paired research candidates.
                # Context can only alter NEXT bar's paper exposure.
                settle_context_ablations(
                    db,instrument_id=instrument_id,states=available,
                    bar_time=bar_at,open_price=bar["open"],
                    close_price=bar["close"])
            if bars:
                db.execute("""
                    UPDATE lsim_feature_cursors SET last_bar_time=?,state_json=?,
                      updated_at=CURRENT_TIMESTAMP WHERE instrument_id=?
                """, (features["last_bar"], json.dumps(features), instrument_id))
                for key, state in states.items():
                    if not state:
                        continue
                    db.execute("""
                        INSERT INTO lsim_states(experiment_id,state_json)
                        VALUES(?,?) ON CONFLICT(experiment_id) DO UPDATE SET
                          state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
                    """, (key, json.dumps(state)))
                persist_shadow_states(db,instrument_id,shadows)
            run_evolution_maintenance(
                db,instrument_id=instrument_id,market_name=market,
                states=states,now=moment)
    return processed


def lab_snapshot(*, db_path="pricegauger.db"):
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        rows = db.execute("""
            SELECT e.experiment_id,e.market_name,e.family,e.signal_tf,e.regime_tf,
                   e.modifier,e.max_exposure,e.cost_bps,e.started_at,e.status,
                   s.state_json
            FROM lsim_experiments e LEFT JOIN lsim_states s
              ON e.experiment_id=s.experiment_id
            ORDER BY e.market_name,e.family,e.signal_tf,e.regime_tf,e.modifier
        """).fetchall()
        regimes = db.execute("""
            SELECT experiment_id,regime,observed_bars,sum_delta_nav
            FROM lsim_regime_memory ORDER BY experiment_id,regime
        """).fetchall()
        cursors = db.execute("""
            SELECT instrument_id,market_name,last_bar_time,updated_at
            FROM lsim_feature_cursors ORDER BY instrument_id
        """).fetchall()
    results = []
    for row in rows:
        state = json.loads(row["state_json"]) if row["state_json"] else {}
        results.append({k: row[k] for k in (
            "experiment_id","market_name","family","signal_tf","regime_tf",
            "modifier","max_exposure","cost_bps","started_at","status")})
        evo = state.get("_evo") or {}
        observed = int(evo.get("bars",0))
        results[-1].update(
            observed_bars=observed,
            above_start_pct=100.0 * int(evo.get("positive_since_start_bars",0))/observed if observed else 0.0,
            positive_bar_pct=100.0 * int(evo.get("positive_bar_returns",0))/observed if observed else 0.0,
            equity=float(state.get("equity",10000.0)),
            return_pct=(float(state.get("equity",10000.0))/10000.0-1)*100.0,
            max_drawdown_pct=float(state.get("max_drawdown",0))*100.0,
            trades=int(state.get("trades",0)), exposure=float(state.get("exposure",0.0)),
            last_bar=state.get("last_bar"))
    return results, [dict(row) for row in regimes], [dict(row) for row in cursors]


def lab_equity_points(experiment_ids, *, db_path="pricegauger.db", limit=1500):
    if not experiment_ids:
        return []
    ensure_lab_schema(db_path)
    keys = tuple(str(item) for item in experiment_ids[:12])
    with connect(db_path) as db:
        rows = db.execute("""
            SELECT experiment_id,bar_time,equity,exposure,regime,decision,traded
            FROM lsim_points WHERE experiment_id IN (""" +
            ",".join("?" for _ in keys) +
            """) ORDER BY bar_time DESC LIMIT ?
        """, (*keys, max(1,int(limit)))).fetchall()
    return [dict(row) for row in reversed(rows)]


def produce_daily_summary(report_date, *, db_path="pricegauger.db"):
    """Objective daily snapshot; future AI reports will analyze this immutable evidence."""
    variants, regimes, cursors = lab_snapshot(db_path=db_path)
    ranked = sorted((v for v in variants if v["last_bar"]), key=lambda v:v["return_pct"], reverse=True)
    result = {"date":report_date, "version": ENGINE_VERSION, "variants":len(variants),
              "observed":len(ranked), "top":ranked[:10], "bottom":ranked[-10:],
              "regime_evidence":regimes, "data_cursors":cursors,
              "ai_interpretation":None, "interpretation_status":"PENDING_AI"}
    with connect(db_path) as db:
        db.execute("""
            INSERT INTO lsim_daily_reports(report_date,created_at,data_json)
            VALUES(?,CURRENT_TIMESTAMP,?)
            ON CONFLICT(report_date) DO NOTHING
        """, (report_date,json.dumps(result)))
    return result
