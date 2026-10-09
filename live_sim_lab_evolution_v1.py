"""Forward-only shadow strategy selection and bounded evolutionary experiment trials.

Research authority only. This module never imports Saxo, V3 or order submission.
The chooser is itself a paper strategy with next-open fills and switching costs.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from live_sim_lab_core_v1 import utc
from live_sim_lab_store_v1 import (
    MAX_ACTIVE_LAB_VARIANTS, candidate_configs, _new_experiment_id,
)

SELECTOR_KINDS = ("RECENT", "REGIME", "HYBRID")
NEW_MODIFIERS = ("trend_only", "volatility_pause", "momentum_confirm", "adverse_exit")
PERFORMANCE_SAMPLE_MINUTES = 5
MAX_SAMPLES = 288
MIN_SELECT_SAMPLES = 25  # 120 minutes of genuine post-enrollment observations
MIN_REGIME_BARS = 60
SELECTOR_COOLDOWN_MINUTES = 60
SELECTOR_SCORE_EDGE_PCT = 0.15
SELECTOR_SWITCH_COST_BPS = 7.0
MAX_SWITCHES_PER_DAY = 8
RETIRE_MIN_BARS = 1200
RETIRE_MIN_TRADES = 8
RETIRE_REGIME_BARS = 120
RETIRE_WEAK_CHECKS = 3
PROMOTION_MIN_BARS = 240
PROMOTION_INTERVAL_MINUTES = 60
PROMOTIONS_PER_BATCH = 4


def ensure_evolution_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lsim_selector_states(
          instrument_id INTEGER NOT NULL, selector_kind TEXT NOT NULL,
          state_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(instrument_id,selector_kind)
        );
        CREATE TABLE IF NOT EXISTS lsim_selector_points(
          instrument_id INTEGER NOT NULL, selector_kind TEXT NOT NULL,
          bar_time TEXT NOT NULL, equity REAL NOT NULL, exposure REAL NOT NULL,
          experiment_id TEXT, regime TEXT NOT NULL, switches INTEGER NOT NULL,
          PRIMARY KEY(instrument_id,selector_kind,bar_time)
        );
        CREATE TABLE IF NOT EXISTS lsim_selector_events(
          instrument_id INTEGER NOT NULL, selector_kind TEXT NOT NULL,
          decision_bar TEXT NOT NULL, prior_id TEXT, proposed_id TEXT,
          reason TEXT NOT NULL, score_json TEXT NOT NULL,
          PRIMARY KEY(instrument_id,selector_kind,decision_bar)
        );
        CREATE TABLE IF NOT EXISTS lsim_perturbation_trials(
          experiment_id TEXT PRIMARY KEY, instrument_id INTEGER NOT NULL,
          config_json TEXT NOT NULL, parent_id TEXT, origin TEXT NOT NULL,
          status TEXT NOT NULL, queued_at TEXT NOT NULL,
          started_at TEXT, ended_at TEXT, outcome_json TEXT,
          weak_checks INTEGER NOT NULL DEFAULT 0, last_checked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS lsim_perturbation_queue
          ON lsim_perturbation_trials(instrument_id,status,queued_at);
        CREATE TABLE IF NOT EXISTS lsim_evolution_runs(
          instrument_id INTEGER PRIMARY KEY,
          last_promotion_at TEXT, last_retirement_at TEXT
        );
    """)


def update_observation(state, previous, *, prior_regime, bar_time):
    """Rolling evidence for this experiment, calculated after the bar closes."""
    old = float(previous.get("equity", 10000.0))
    current = float(state.get("equity", 10000.0))
    evo = dict(previous.get("_evo") or {})
    evo["bars"] = int(evo.get("bars", 0)) + 1
    evo["positive_since_start_bars"] = int(evo.get("positive_since_start_bars", 0)) + int(current > 10000.0)
    evo["positive_bar_returns"] = int(evo.get("positive_bar_returns", 0)) + int(current > old)
    regimes = dict(evo.get("regime_stats") or {})
    item = dict(regimes.get(prior_regime) or {})
    item["bars"] = int(item.get("bars", 0)) + 1
    item["sum_return_fraction"] = float(item.get("sum_return_fraction", 0.0)) + (current / max(old, 1e-9) - 1.0)
    regimes[prior_regime] = item
    evo["regime_stats"] = regimes
    samples = list(evo.get("samples") or [])
    minute = int(utc(bar_time).timestamp()) // 60
    if (minute + 1) % PERFORMANCE_SAMPLE_MINUTES == 0:
        samples.append([utc(bar_time).isoformat(), current])
    evo["samples"] = samples[-MAX_SAMPLES:]
    state["_evo"] = evo
    return state


def _recent_return_pct(evo, samples=24):
    points = evo.get("samples") or []
    if len(points) < samples + 1:
        return None
    start = float(points[-samples-1][1])
    return 100.0 * (float(points[-1][1]) / max(start, 1e-9) - 1.0)


def _regime_return_pct(evo, regime):
    row = (evo.get("regime_stats") or {}).get(regime) or {}
    n = int(row.get("bars", 0))
    if n < MIN_REGIME_BARS:
        return None
    # Expected cumulative percentage points per 120 observed regime bars.
    return 100.0 * 120.0 * float(row.get("sum_return_fraction", 0.0)) / n


def candidate_score(kind, state, regime):
    evo = state.get("_evo") or {}
    samples = evo.get("samples") or []
    if len(samples) < MIN_SELECT_SAMPLES or int(state.get("trades", 0)) < 2:
        return None
    recent = _recent_return_pct(evo, 24)
    longer = _recent_return_pct(evo, 72)
    if recent is None:
        return None
    recent_score = 0.8 * recent + 0.2 * (longer if longer is not None else recent)
    risk_penalty = 0.2 * 100.0 * float(state.get("max_drawdown", 0.0))
    regime_score = _regime_return_pct(evo, regime)
    if kind == "REGIME" and regime_score is None:
        return None
    if kind == "HYBRID" and regime_score is None:
        return None
    if kind == "RECENT":
        return round(recent_score-risk_penalty, 6)
    if kind == "REGIME":
        return round(regime_score-risk_penalty, 6)
    return round(0.5 * recent_score + 0.5 * regime_score - risk_penalty, 6)


def _default_shadow_state():
    return {"equity":10000.0, "peak":10000.0, "exposure":0.0,
            "last_close":None, "last_bar":None, "max_drawdown":0.0,
            "selected_id":None, "pending_id":None, "pending_exposure":0.0,
            "last_switch_at":None, "switches":0, "trades":0,
            "daily_switches":0, "daily_switch_date":None}


def load_shadow_states(db, instrument_id):
    rows = db.execute(
        "SELECT selector_kind,state_json FROM lsim_selector_states WHERE instrument_id=?",
        (instrument_id,)).fetchall()
    saved = {str(r["selector_kind"]):json.loads(r["state_json"]) for r in rows}
    return {name:saved.get(name, _default_shadow_state()) for name in SELECTOR_KINDS}


def _choose(kind, shadow, candidate_states, *, regime, stamp):
    scores = {key:score for key, s in candidate_states.items()
              if (score:=candidate_score(kind, s, regime)) is not None}
    current = shadow.get("selected_id")
    if not scores:
        return current if current in candidate_states else None, "INSUFFICIENT_EVIDENCE", scores
    ranked = sorted(scores, key=lambda x:(-scores[x], x))
    best = ranked[0]
    if current is None or current not in candidate_states:
        return best, "FIRST_QUALIFIED", scores
    if current not in scores:
        return best, "INCUMBENT_NOT_QUALIFIED", scores
    if best == current:
        return current, "HOLD_CHAMPION", scores
    last_switch = shadow.get("last_switch_at")
    if last_switch is not None and (utc(stamp)-utc(last_switch)).total_seconds() < SELECTOR_COOLDOWN_MINUTES * 60:
        return current, "COOLDOWN", scores
    if int(shadow.get("daily_switches", 0)) >= MAX_SWITCHES_PER_DAY:
        return current, "DAILY_SWITCH_LIMIT", scores
    incumbent_score = scores[current]
    improvement = scores[best] - incumbent_score
    incumbent_recent = _recent_return_pct(candidate_states[current].get("_evo") or {}, 24)
    if (improvement >= SELECTOR_SCORE_EDGE_PCT and
            (incumbent_recent is not None and incumbent_recent < -0.05 or
             improvement >= 0.50)):
        return best, "CHALLENGER_OUTPERFORMS", scores
    return current, "KEEP_INCUMBENT", scores


def settle_shadow(db, *, instrument_id, states, candidates, features,
                  prior_regime, bar_time, open_price, close_price):
    """At bar open execute selection made at PREVIOUS close; score after this close."""
    stamp = utc(bar_time).isoformat()
    minute = int(utc(bar_time).timestamp()) // 60
    daily = utc(bar_time).date().isoformat()
    for kind in SELECTOR_KINDS:
        shadow = dict(states[kind])
        if shadow.get("daily_switch_date") != daily:
            shadow["daily_switch_date"] = daily
            shadow["daily_switches"] = 0
        equity = float(shadow["equity"])
        old_exposure = float(shadow["exposure"])
        last_close = shadow.get("last_close")
        if last_close:
            equity *= 1.0 + old_exposure * (float(open_price)/float(last_close) - 1.0)
        next_exposure = float(shadow.get("pending_exposure") or 0.0)
        next_id = shadow.get("pending_id")
        turnover = abs(next_exposure-old_exposure)
        changed = next_id != shadow.get("selected_id")
        if changed:
            shadow["selected_id"] = next_id
            shadow["switches"] = int(shadow.get("switches", 0)) + 1
            shadow["daily_switches"] += 1
            shadow["last_switch_at"] = stamp
        if turnover > 1e-8:
            shadow["trades"] = int(shadow.get("trades", 0)) + 1
        # Turnover and extra selection impact charged on next-open execution.
        equity *= 1.0 - turnover * 5.0/10000.0
        if changed:
            equity *= 1.0 - abs(next_exposure)*SELECTOR_SWITCH_COST_BPS/10000.0
        equity *= 1.0 + next_exposure * (float(close_price)/float(open_price)-1.0)
        peak = max(float(shadow.get("peak", 10000.0)), equity)
        shadow.update(equity=equity, peak=peak, exposure=next_exposure,
                      last_close=float(close_price), last_bar=stamp,
                      max_drawdown=max(float(shadow.get("max_drawdown",0.0)), 1.0-equity/max(peak,1e-9)))
        chosen, reason, scores = _choose(kind, shadow, candidates, regime=features["regime"], stamp=stamp)
        pending = (candidates[chosen].get("pending", candidates[chosen].get("exposure", 0.0))
                   if chosen is not None else 0.0)
        # Distinguish no decision on this signal bar from zero exposure.
        if pending is None:
            pending = float(candidates[chosen].get("exposure", 0.0))
        shadow["pending_id"] = chosen
        shadow["pending_exposure"] = float(pending)
        states[kind] = shadow
        if chosen != shadow["selected_id"]:
            db.execute("""
                INSERT INTO lsim_selector_events(
                  instrument_id,selector_kind,decision_bar,prior_id,proposed_id,reason,score_json)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(instrument_id,selector_kind,decision_bar) DO NOTHING
            """, (instrument_id,kind,stamp,shadow["selected_id"],chosen,reason,
                  json.dumps({"old":scores.get(shadow["selected_id"]),
                              "new":scores.get(chosen),"regime":features["regime"]})))
        if changed or (minute + 1) % 5 == 0:
            db.execute("""
                INSERT INTO lsim_selector_points(
                  instrument_id,selector_kind,bar_time,equity,exposure,experiment_id,regime,switches)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(instrument_id,selector_kind,bar_time) DO NOTHING
            """, (instrument_id,kind,stamp,equity,next_exposure,shadow["selected_id"],
                  prior_regime,shadow["switches"]))
    return states


def persist_shadow_states(db, instrument_id, states):
    for kind, value in states.items():
        if value.get("last_bar") is None:
            continue
        db.execute("""
            INSERT INTO lsim_selector_states(instrument_id,selector_kind,state_json)
            VALUES(?,?,?) ON CONFLICT(instrument_id,selector_kind) DO UPDATE SET
            state_json=excluded.state_json,updated_at=CURRENT_TIMESTAMP
        """, (instrument_id,kind,json.dumps(value)))


def _queue_configs():
    """Finite, reproducible search grid. Only implemented modifier semantics."""
    for base in candidate_configs():
        for signal_tf in (base["signal_tf"], 10):
            for modifier in (base["modifier"], *NEW_MODIFIERS):
                cfg = dict(base,signal_tf=signal_tf,modifier=modifier)
                yield cfg


def seed_trial_ledger(db, *, instrument_id, now):
    """Complete tried/queued journal, deterministic IDs, never replay retired IDs."""
    rows = db.execute(
        "SELECT experiment_id,config_json,started_at,status FROM lsim_experiments WHERE instrument_id=?",
        (instrument_id,)).fetchall()
    for r in rows:
        db.execute("""
            INSERT INTO lsim_perturbation_trials(
              experiment_id,instrument_id,config_json,parent_id,origin,status,queued_at,started_at)
            VALUES(?,?,?,?,'BASELINE',?,?,?)
            ON CONFLICT(experiment_id) DO NOTHING
        """, (r["experiment_id"],instrument_id,r["config_json"],None,
              "RUNNING" if r["status"]=="ACTIVE" else r["status"],
              r["started_at"],r["started_at"]))
    # Deduplicate the full deterministic grid before writing.
    seen = set()
    for cfg in _queue_configs():
        ident = _new_experiment_id(instrument_id,cfg)
        if ident in seen:
            continue
        seen.add(ident)
        parent_cfg = dict(cfg,signal_tf=cfg["signal_tf"] if cfg["signal_tf"] in (2,5) else 5,
                          modifier="none")
        parent = _new_experiment_id(instrument_id,parent_cfg)
        db.execute("""
            INSERT INTO lsim_perturbation_trials(
              experiment_id,instrument_id,config_json,parent_id,origin,status,queued_at)
            VALUES(?,?,?,?,'BOUNDED_PERTURBATION','QUEUED',?)
            ON CONFLICT(experiment_id) DO NOTHING
        """, (ident,instrument_id,json.dumps(cfg,sort_keys=True),parent,now))


def _retire_weak(db, instrument_id, states, now):
    trials = db.execute("""
        SELECT experiment_id,weak_checks,last_checked_at FROM lsim_perturbation_trials
        WHERE instrument_id=? AND status='RUNNING'
    """, (instrument_id,)).fetchall()
    retired = 0
    for trial in trials:
        key = trial["experiment_id"]
        state = states.get(key) or {}
        evo = state.get("_evo") or {}
        if int(evo.get("bars",0)) < RETIRE_MIN_BARS or int(state.get("trades",0)) < RETIRE_MIN_TRADES:
            continue
        enough = [v for v in (evo.get("regime_stats") or {}).values()
                  if int(v.get("bars",0)) >= RETIRE_REGIME_BARS]
        if len(enough) < 2:
            continue
        # A regime is a rescue only if it has demonstrated POSITIVE forward net
        # expectancy. Negative or zero across all sufficiently observed regimes
        # plus never positive total return is an operational failure.
        weak = (float(state.get("peak",10000.0)) <= 10000.0 and
                all(float(v["sum_return_fraction"]) <= 0.0 for v in enough))
        last = trial["last_checked_at"]
        if last and (utc(now)-utc(last)).total_seconds() < 60*60:
            continue
        checks = int(trial["weak_checks"]) + 1 if weak else 0
        db.execute("""
            UPDATE lsim_perturbation_trials SET weak_checks=?,last_checked_at=?
            WHERE experiment_id=?
        """, (checks,utc(now).isoformat(),key))
        if checks < RETIRE_WEAK_CHECKS:
            continue
        payload = {
            "reason":"NEVER_PROFITABLE_AND_NO_POSITIVE_REGIME_EDGE",
            "bars":evo["bars"],"trades":state["trades"],
            "return_pct":100.0*(float(state["equity"])/10000.0-1.0),
            "max_drawdown_pct":100.0*float(state.get("max_drawdown",0.0)),
            "positive_since_start_fraction":evo.get("positive_since_start_bars",0)/evo["bars"],
            "regime_stats":evo.get("regime_stats",{}),
        }
        db.execute("UPDATE lsim_experiments SET status='RETIRED' WHERE experiment_id=? AND status='ACTIVE'",(key,))
        db.execute("""
            UPDATE lsim_perturbation_trials
            SET status='RETIRED',ended_at=?,outcome_json=? WHERE experiment_id=?
        """,(utc(now).isoformat(),json.dumps(payload),key))
        retired += 1
    return retired


def run_evolution_maintenance(db, *, instrument_id, market_name, states, now):
    """DB-transactional retirement/promotion after processing forward bars.

    Keeps historical trials immutable and never refills slots with a retired ID.
    Rate-limited experiments are born with their own later started_at timestamp.
    """
    moment = utc(now)
    now_stamp = moment.isoformat()
    seed_trial_ledger(db,instrument_id=instrument_id,now=now_stamp)
    db.execute("""
        INSERT INTO lsim_evolution_runs(instrument_id) VALUES(?)
        ON CONFLICT(instrument_id) DO NOTHING
    """,(instrument_id,))
    retired = _retire_weak(db,instrument_id,states,moment)
    active = db.execute("SELECT COUNT(*) AS n FROM lsim_experiments WHERE status='ACTIVE'").fetchone()["n"]
    if active >= MAX_ACTIVE_LAB_VARIANTS:
        return retired, 0
    oldest = max((int((s.get("_evo") or {}).get("bars",0)) for s in states.values()),default=0)
    if oldest < PROMOTION_MIN_BARS:
        return retired, 0
    last = db.execute("SELECT last_promotion_at FROM lsim_evolution_runs WHERE instrument_id=?",
                      (instrument_id,)).fetchone()["last_promotion_at"]
    if last and (moment-utc(last)).total_seconds() < PROMOTION_INTERVAL_MINUTES*60:
        return retired, 0
    # Prioritize children of recently performing active controls; never use
    # future observations. Unproven parents rank last, deterministic ties.
    rows = db.execute("""
        SELECT experiment_id,config_json,parent_id FROM lsim_perturbation_trials
        WHERE instrument_id=? AND status='QUEUED'
    """,(instrument_id,)).fetchall()
    scored = []
    for row in rows:
        parent_state = states.get(row["parent_id"]) or {}
        rank = candidate_score("RECENT",parent_state,"RANGE")
        scored.append((-(rank if rank is not None else -1e6),row["experiment_id"],row))
    scored.sort(key=lambda v:(v[0],v[1]))
    created=0
    for _,key,trial in scored:
        if active >= MAX_ACTIVE_LAB_VARIANTS or created >= PROMOTIONS_PER_BATCH:
            break
        cfg=json.loads(trial["config_json"])
        # Guard implemented search-space only; prohibit arbitrary executable
        # parameters from persisted AI suggestions.
        if cfg.get("family") not in {"sticky","fast_exit"} or cfg.get("modifier") not in {
            "none","whipsaw_pause","impulse_exit",*NEW_MODIFIERS}:
            continue
        db.execute("""
            INSERT INTO lsim_experiments(
              experiment_id,instrument_id,market_name,family,signal_tf,regime_tf,
              modifier,max_exposure,cost_bps,config_json,engine_version,started_at,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,(key,instrument_id,market_name,cfg["family"],cfg["signal_tf"],
              cfg["regime_tf"],cfg["modifier"],cfg["max_exposure"],cfg["cost_bps"],
              json.dumps(cfg,sort_keys=True),"live-sim-lab-v1",now_stamp,"ACTIVE"))
        db.execute("""
            UPDATE lsim_perturbation_trials
            SET status='RUNNING',started_at=? WHERE experiment_id=?
        """,(now_stamp,key))
        active+=1
        created+=1
    if created:
        db.execute("""
            UPDATE lsim_evolution_runs SET last_promotion_at=? WHERE instrument_id=?
        """,(now_stamp,instrument_id))
    return retired,created


def evolution_snapshot(*, db_path="pricegauger.db"):
    """Read-only UI view of selectors, complete trial history and pending queue."""
    from database import connect
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_evolution_schema(db)
        selectors = [dict(r) for r in db.execute("""
            SELECT instrument_id,selector_kind,state_json,updated_at
            FROM lsim_selector_states ORDER BY instrument_id,selector_kind
        """).fetchall()]
        trials = [dict(r) for r in db.execute("""
            SELECT experiment_id,instrument_id,config_json,parent_id,origin,status,
                   queued_at,started_at,ended_at,outcome_json,weak_checks
            FROM lsim_perturbation_trials ORDER BY status,queued_at,experiment_id
        """).fetchall()]
        switches = [dict(r) for r in db.execute("""
            SELECT instrument_id,selector_kind,decision_bar,prior_id,proposed_id,reason,score_json
            FROM lsim_selector_events ORDER BY decision_bar DESC LIMIT 50
        """).fetchall()]
    for s in selectors:
        s.update(json.loads(s.pop("state_json")))
    for t in trials:
        t["config"] = json.loads(t.pop("config_json"))
        t["outcome"] = json.loads(t["outcome_json"]) if t.pop("outcome_json") else None
    return selectors,trials,switches


def selector_equity_points(*, db_path="pricegauger.db", limit=2000):
    from database import connect
    from live_sim_lab_store_v1 import ensure_lab_schema
    ensure_lab_schema(db_path)
    with connect(db_path) as db:
        ensure_evolution_schema(db)
        rows=db.execute("""
            SELECT instrument_id,selector_kind,bar_time,equity,exposure,experiment_id,regime,switches
            FROM lsim_selector_points ORDER BY bar_time DESC LIMIT ?
        """,(min(2000,max(1,int(limit))),)).fetchall()
    return [dict(r) for r in reversed(rows)]
