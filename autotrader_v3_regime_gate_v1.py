"""Opt-in V3 entry regime gate, independent of the manual emergency STOP.

Only stored canonical, *completed* 1m prices are read. No Saxo HTTP calls,
orders, automatic policy changes or inferred positions are performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, log
import logging

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect, run_postgres_schema_once_v1

STATES_V1 = ("BULL", "BEAR", "SIDEWAYS")
MODES_V1 = ("OFF", "SHADOW", "LIVE")


@dataclass(frozen=True, slots=True)
class RegimePolicyV1:
    instance_id: str
    strategy_key: str
    mode: str = "OFF"
    allowed_states: tuple[str, ...] = STATES_V1
    trend_only: bool = False
    block_unknown: bool = False
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class RegimeDecisionV1:
    state: str
    evidence: str
    would_allow: bool
    allow_new_exposure: bool
    mode: str


def _identity(instance_id: str, strategy_key: str) -> tuple[str, str]:
    identity, strategy = str(instance_id or "").strip(), str(strategy_key or "").strip()
    if not identity or not strategy:
        raise ValueError("exact instance and strategy required")
    return identity, strategy


def ensure_regime_policy_schema_v1(db_path="pricegauger.db") -> None:
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_regime_entry_policy_v1(
                instance_id TEXT PRIMARY KEY, strategy_key TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('OFF','SHADOW','LIVE')),
                allow_bull INTEGER NOT NULL, allow_bear INTEGER NOT NULL,
                allow_sideways INTEGER NOT NULL, trend_only INTEGER NOT NULL,
                block_unknown INTEGER NOT NULL, updated_at TEXT NOT NULL)""")
    run_postgres_schema_once_v1("v3_regime_entry_policy_v1", initialize)


def load_regime_policy_v1(*, instance_id: str, strategy_key: str,
                          db_path="pricegauger.db") -> RegimePolicyV1:
    identity, strategy = _identity(instance_id, strategy_key)
    ensure_regime_policy_schema_v1(db_path)
    with connect(db_path) as db:
        row = db.execute("""SELECT strategy_key,mode,allow_bull,allow_bear,
            allow_sideways,trend_only,block_unknown,updated_at
            FROM pg_v3_regime_entry_policy_v1 WHERE instance_id=?""", (identity,)).fetchone()
    if row is None or str(row["strategy_key"]) != strategy:
        return RegimePolicyV1(identity, strategy)
    mode = str(row["mode"])
    if mode not in MODES_V1:
        raise ValueError("unknown regime gate mode")
    raw = tuple(row["allow_" + label.lower()] for label in STATES_V1)
    flags = raw + (row["trend_only"], row["block_unknown"])
    if any(v not in (0, 1, False, True) for v in flags):
        raise ValueError("invalid regime gate flags")
    return RegimePolicyV1(
        identity, strategy, mode,
        tuple(s for s, enabled in zip(STATES_V1, raw) if enabled),
        bool(row["trend_only"]), bool(row["block_unknown"]), str(row["updated_at"]),
    )


def save_regime_policy_v1(*, instance_id: str, strategy_key: str, mode: str,
                          allowed_states: tuple[str, ...], trend_only: bool,
                          block_unknown: bool, db_path="pricegauger.db") -> RegimePolicyV1:
    """Only explicit operator UI actions call this; never the observer/worker."""
    identity, strategy = _identity(instance_id, strategy_key)
    if mode not in MODES_V1 or not isinstance(trend_only, bool) or not isinstance(block_unknown, bool):
        raise ValueError("invalid regime policy mode or flags")
    chosen = tuple(allowed_states)
    if len(chosen) != len(set(chosen)) or any(s not in STATES_V1 for s in chosen):
        raise ValueError("invalid allowed market states")
    ensure_regime_policy_schema_v1(db_path)
    updated_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as db:
        db.execute("""INSERT INTO pg_v3_regime_entry_policy_v1(
            instance_id,strategy_key,mode,allow_bull,allow_bear,allow_sideways,
            trend_only,block_unknown,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(instance_id) DO UPDATE SET
            strategy_key=excluded.strategy_key,mode=excluded.mode,
            allow_bull=excluded.allow_bull,allow_bear=excluded.allow_bear,
            allow_sideways=excluded.allow_sideways,trend_only=excluded.trend_only,
            block_unknown=excluded.block_unknown,updated_at=excluded.updated_at""",
            (identity, strategy, mode, *(int(s in chosen) for s in STATES_V1),
             int(trend_only), int(block_unknown), updated_at))
    return RegimePolicyV1(identity, strategy, mode, chosen, trend_only, block_unknown, updated_at)


def _utc(value: str | datetime) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timezone-aware canonical bar required")
    return stamp.astimezone(timezone.utc)


def _trend(closes: tuple[float, ...], minimum_efficiency: float) -> str:
    movements = tuple(log(b / a) for a, b in zip(closes, closes[1:]))
    total = sum(abs(v) for v in movements)
    net = sum(movements)
    if total <= 1e-12 or abs(net) / total < minimum_efficiency:
        return "SIDEWAYS"
    return "BULL" if net > 0 else "BEAR"


def classify_regime_v1(bars, *, now: datetime) -> tuple[str, str]:
    """30m provisional / 60m confirmed. Unknown data is NOT sideways.

    No gap filling, future candles or historical regime carry-over. A strong
    opposing 30m move prevents an old 60m trend authorizing countertrend.
    """
    current = _utc(now)
    latest_open = current.replace(second=0, microsecond=0) - timedelta(minutes=1)
    ordered = tuple(bars)
    if not ordered or _utc(ordered[-1].bar_time) != latest_open:
        return "UNKNOWN", "Ingen fersk ferdig 1m-bar"
    tail = ordered[-61:]
    for b in tail:
        if not isfinite(float(b.close)) or float(b.close) <= 0:
            return "UNKNOWN", "Ugyldig kanonisk sluttkurs"
    contiguous = [tail[-1]]
    for earlier in reversed(tail[:-1]):
        if _utc(earlier.bar_time) != _utc(contiguous[-1].bar_time) - timedelta(minutes=1):
            break
        contiguous.append(earlier)
    if len(contiguous) < 31:
        return "UNKNOWN", "Under 30 sammenhengende fullførte minutter"
    closes = tuple(float(b.close) for b in reversed(contiguous))
    short = _trend(closes[-31:], 0.42)
    if len(closes) < 61:
        return short, "Foreløpig 30m-prisretning"
    long = _trend(closes[-61:], 0.32)
    if long in ("BULL", "BEAR") and short in ("BULL", "BEAR") and long != short:
        return "SIDEWAYS", "30m og 60m er i konflikt"
    return long, "60m-prisretning med 30m mottrendkontroll"


def decide_regime_entry_v1(policy: RegimePolicyV1, *, state: str,
                           direction: str, evidence: str = "") -> RegimeDecisionV1:
    if state not in STATES_V1 + ("UNKNOWN",) or direction not in ("LONG", "SHORT"):
        raise ValueError("unknown state or entry direction")
    would_allow = ((not policy.block_unknown) if state == "UNKNOWN"
                   else state in policy.allowed_states and
                   (not policy.trend_only or state == "SIDEWAYS" or
                    (state == "BULL" and direction == "LONG") or
                    (state == "BEAR" and direction == "SHORT")))
    return RegimeDecisionV1(state, evidence, would_allow,
                             policy.mode != "LIVE" or would_allow, policy.mode)


def read_regime_state_v1(*, instrument_id, db_path="pricegauger.db", now=None):
    """Same market evidence in UI and LIVE; unreadable prices are UNKNOWN."""
    try:
        clock = _utc(now or datetime.now(timezone.utc))
        last_open = clock.replace(second=0, microsecond=0) - timedelta(minutes=1)
        rows = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
            instrument_id=int(instrument_id), start=last_open-timedelta(minutes=63),
            end=last_open, limit=65)
        return classify_regime_v1(rows, now=clock)
    except Exception:
        return "UNKNOWN", "Kanoniske prisdata kunne ikke leses"


def check_regime_entry_v1(*, instance_id: str, strategy_key: str,
                          instrument_id: int, direction: str, db_path="pricegauger.db",
                          now: datetime | None = None) -> RegimeDecisionV1:
    """A known policy controls UNKNOWN; unreadable policy is a separate error.

    OFF defaults to allow; SHADOW evaluates without veto; manual STOP remains
    a separate, higher-priority gate. CLOSE/REDUCE must not call this helper.
    """
    try:
        policy = load_regime_policy_v1(instance_id=instance_id,
                                       strategy_key=strategy_key, db_path=db_path)
        if policy.mode == "OFF":
            return RegimeDecisionV1("UNKNOWN", "Filter AV", True, True, "OFF")
        state, evidence = read_regime_state_v1(
            instrument_id=instrument_id, db_path=db_path, now=now)
        return decide_regime_entry_v1(policy, state=state, direction=direction,
                                       evidence=evidence)
    except Exception:
        # A broken policy read cannot establish permission.
        return RegimeDecisionV1("UNKNOWN", "Regimekontroll utilgjengelig", False, False, "ERROR")


def _ensure_regime_block_schema_v1(db_path):
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_regime_block_event_v1(
                instance_id TEXT NOT NULL, strategy_key TEXT NOT NULL,
                decision_key TEXT NOT NULL, action TEXT NOT NULL, direction TEXT NOT NULL,
                state TEXT NOT NULL, blocked_at TEXT NOT NULL,
                PRIMARY KEY(instance_id,strategy_key,decision_key,action,direction))""")
    run_postgres_schema_once_v1("v3_regime_block_event_v1", initialize)


def record_regime_block_v1(*, instance_id, strategy_key, decision_key, action,
                           direction, decision, db_path="pricegauger.db"):
    """Count unique LIVE entry vetoes, never polls, shadow decisions or exits.

    Instrumentation must not alter execution, even if its storage is unavailable.
    """
    if (decision.mode != "LIVE" or decision.allow_new_exposure
            or action not in ("OPEN", "ADD") or direction not in ("LONG", "SHORT")
            or not decision_key):
        return
    try:
        _ensure_regime_block_schema_v1(db_path)
        with connect(db_path) as db:
            db.execute("""INSERT INTO pg_v3_regime_block_event_v1
                (instance_id,strategy_key,decision_key,action,direction,state,blocked_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(instance_id,strategy_key,decision_key,action,direction)
                DO NOTHING""", (str(instance_id), str(strategy_key), str(decision_key),
                action, direction, decision.state, datetime.now(timezone.utc).isoformat()))
    except Exception:
        logging.getLogger(__name__).warning("Regime block counter write failed", exc_info=False)


def load_regime_block_count_v1(*, instance_id, db_path="pricegauger.db"):
    """Lifetime unique vetoes since counter rollout; None on read failure."""
    try:
        _ensure_regime_block_schema_v1(db_path)
        with connect(db_path) as db:
            row = db.execute("""SELECT COUNT(*) AS n FROM pg_v3_regime_block_event_v1
                WHERE instance_id=?""", (str(instance_id),)).fetchone()
        return int(row["n"])
    except Exception:
        return None


def strategy_entry_directions_v1(strategy_key):
    """Known one-sided catalogue strategies; others retain both directions."""
    key = str(strategy_key)
    if "-long-flat-" in key or key.startswith("impulse-catcher-long-"):
        return ("LONG",)
    if "-short-flat-" in key or key.startswith("impulse-catcher-short-"):
        return ("SHORT",)
    return ("LONG", "SHORT")


__all__ = ["STATES_V1", "MODES_V1", "RegimePolicyV1", "RegimeDecisionV1",
           "load_regime_policy_v1", "save_regime_policy_v1", "classify_regime_v1",
           "decide_regime_entry_v1", "check_regime_entry_v1",
           "record_regime_block_v1", "load_regime_block_count_v1",
           "strategy_entry_directions_v1", "read_regime_state_v1"]
