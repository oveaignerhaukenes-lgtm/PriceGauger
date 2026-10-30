"""Immutable, owner-scoped Algorithm Lab experiment history.

No LIVE data mutation. User possession of a high-entropy research access key
authorizes only their laboratory records. No account trading authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import secrets
from uuid import uuid4

from algorithm_lab_v1 import validate_plan
from database import connect

MAX_RECORDS = 80


def new_research_key() -> str:
    return secrets.token_urlsafe(32)


def owner_hash(token: str) -> str:
    raw = str(token or "").strip()
    if len(raw) < 32 or len(raw) > 256:
        raise ValueError("Forskningsnøkkelen må ha minst 32 tegn.")
    return sha256(("pg-algorithm-lab-owner-v2:" + raw).encode("utf-8")).hexdigest()


def ensure_schema(db_path="pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS algorithm_lab_experiments_v2 (
              experiment_id TEXT PRIMARY KEY,
              owner_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              label TEXT NOT NULL,
              plan_json TEXT NOT NULL,
              context_json TEXT NOT NULL,
              results_json TEXT NOT NULL
            )""")
        db.execute(
            """CREATE INDEX IF NOT EXISTS algorithm_lab_experiments_owner_time
               ON algorithm_lab_experiments_v2(owner_hash, created_at)""")


def save_experiment(*, token: str, label: str, plan: dict,
                    context: dict, results: dict, db_path="pricegauger.db") -> str:
    who = owner_hash(token)
    recipe = validate_plan(plan)
    title = str(label or "").strip()[:120]
    if not title:
        raise ValueError("Eksperimentet må ha et navn.")
    ctx = dict(context)
    allowed_ctx = frozenset(("market", "uic", "start", "end", "mode", "costs",
                             "research_notes", "dataset_hash", "split", "fx_uic"))
    if set(ctx) - allowed_ctx:
        raise ValueError("Eksperimentkonteksten har uventede felt.")
    report = dict(results)
    allowed_result = frozenset(("pnl_nok", "return_pct", "drawdown_pct",
                                "total_cost_nok", "trades", "gaps",
                                "train_return_pct", "test_return_pct",
                                "financing_nok"))
    if set(report) - allowed_result:
        raise ValueError("Eksperimentresultatet har uventede felt.")
    values = [json.dumps(x, sort_keys=True, ensure_ascii=False, allow_nan=False)
              for x in (recipe, ctx, report)]
    if any(len(x) > 12000 for x in values):
        raise ValueError("Eksperimentet overstiger lagringsgrensen.")
    ensure_schema(db_path)
    key = str(uuid4())
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO algorithm_lab_experiments_v2
               (experiment_id,owner_hash,created_at,label,plan_json,context_json,results_json)
               VALUES (?,?,?,?,?,?,?)""",
            (key, who, datetime.now(timezone.utc).isoformat(), title,
             *values))
    return key


def list_experiments(*, token: str, limit=MAX_RECORDS, db_path="pricegauger.db") -> tuple[dict, ...]:
    who = owner_hash(token)
    n = int(limit)
    if not 1 <= n <= MAX_RECORDS:
        raise ValueError("Resultatgrense overskredet.")
    ensure_schema(db_path)
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT experiment_id,created_at,label,plan_json,context_json,results_json
               FROM algorithm_lab_experiments_v2 WHERE owner_hash=?
               ORDER BY created_at DESC, experiment_id DESC LIMIT ?""",
            (who, n)).fetchall()
    return tuple({"experiment_id": str(x["experiment_id"]),
                  "created_at": str(x["created_at"]),
                  "label": str(x["label"]),
                  "plan": json.loads(x["plan_json"]),
                  "context": json.loads(x["context_json"]),
                  "results": json.loads(x["results_json"])} for x in rows)


def load_experiment(*, token: str, experiment_id: str, db_path="pricegauger.db") -> dict | None:
    who = owner_hash(token)
    ident = str(experiment_id or "")
    if len(ident) > 64:
        raise ValueError("Ugyldig eksperiment-ID.")
    ensure_schema(db_path)
    with connect(db_path) as db:
        row = db.execute(
            """SELECT experiment_id,created_at,label,plan_json,context_json,results_json
               FROM algorithm_lab_experiments_v2
               WHERE owner_hash=? AND experiment_id=?""",
            (who, ident)).fetchone()
    if row is None:
        return None
    return {"experiment_id": str(row["experiment_id"]),
            "created_at": str(row["created_at"]), "label": str(row["label"]),
            "plan": json.loads(row["plan_json"]),
            "context": json.loads(row["context_json"]),
            "results": json.loads(row["results_json"])}


__all__ = ["new_research_key", "owner_hash", "save_experiment",
           "load_experiment", "list_experiments", "ensure_schema"]
