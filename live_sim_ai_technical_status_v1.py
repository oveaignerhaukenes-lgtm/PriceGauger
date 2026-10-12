"""Independent, read-only AI Trader PAPER heartbeat and operator status.

Status is based on the Lab worker's persisted heartbeat and actual quote/model
activity. Absence of an LLM decision is never presented as an active model.
Research status must never alter the global LIVE AutoTrader health severity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from database import connect
from live_sim_hyper_quotes_v1 import _utc

WORKER_KEY = "AI_TECH_PAPER"
HEARTBEAT_STALE_SECONDS = 25
QUOTE_FRESH_SECONDS = 30


def ensure_ai_status_schema(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS lsim_ai_technical_heartbeat(
            worker_key TEXT PRIMARY KEY,
            tick_at TEXT NOT NULL,
            key_configured INTEGER NOT NULL,
            result TEXT NOT NULL,
            error_type TEXT NOT NULL DEFAULT ''
        )
    """)


def record_ai_heartbeat(*,db_path="pricegauger.db",key_configured=False,
                        result="OK",error_type="",now=None):
    stamp=_utc(now or datetime.now(timezone.utc)).isoformat()
    with connect(db_path) as db:
        ensure_ai_status_schema(db)
        db.execute("""
            INSERT INTO lsim_ai_technical_heartbeat(
                worker_key,tick_at,key_configured,result,error_type)
            VALUES(?,?,?,?,?)
            ON CONFLICT(worker_key) DO UPDATE
            SET tick_at=excluded.tick_at,
                key_configured=excluded.key_configured,
                result=excluded.result,error_type=excluded.error_type
        """,(WORKER_KEY,stamp,int(bool(key_configured)),result,error_type))


def _age(now,value):
    if not value:
        return None
    return max(0.0,(_utc(now)-_utc(value)).total_seconds())


def classify_ai_status(*,heartbeat=None,quote_at=None,decision=None,now=None):
    moment=_utc(now or datetime.now(timezone.utc))
    base={
        "code":"NOT_STARTED","label":"Ikke startet","severity":"IDLE",
        "detail":"Ingen AI-worker-heartbeat er registrert",
        "active":False,"last_tick":None,"last_quote":quote_at,
        "last_decision":None,"last_model_status":None,
        "last_event":None,"last_target":None,
    }
    if heartbeat is None:
        return base
    base["last_tick"]=heartbeat.get("tick_at")
    age=_age(moment,base["last_tick"])
    if age is None or age>HEARTBEAT_STALE_SECONDS:
        base.update(code="OFFLINE",label="Ingen workerkontakt",
                    severity="YELLOW",
                    detail="Ingen heartbeat fra AI Trader de siste 25 sekundene")
        return base
    if str(heartbeat.get("result"))!="OK":
        base.update(code="ENGINE_ERROR",label="AI-workerfeil",
                    severity="RED",detail="Feiltype: "+str(
                        heartbeat.get("error_type") or "Ukjent"))
        return base
    if not heartbeat.get("key_configured"):
        base.update(code="NO_KEY",label="AI ikke tilkoblet",
                    severity="YELLOW",
                    detail="OPENAI_API_KEY mangler på Live-Sim-worker")
        return base
    if decision is not None:
        base.update(
            last_decision=decision.get("as_of"),
            last_model_status=decision.get("model_status"),
            last_event=decision.get("event_kind"),
            last_target=decision.get("target"),
        )
        model=base["last_model_status"] or ""
        if model=="CLAIMED" and (_age(moment,decision.get("requested_at")) or 0)<45:
            base.update(code="THINKING",label="AI vurderer",
                        severity="GREEN",active=True,
                        detail="Modellforespørsel pågår")
            return base
        if model.startswith("ERROR_") or model=="STALE_RESPONSE":
            base.update(code="MODEL_ERROR",label="AI-svar forkastet",
                        severity="YELLOW",
                        detail="Siste vurdering: "+model)
            return base
    gap=_age(moment,quote_at)
    if gap is None or gap>QUOTE_FRESH_SECONDS:
        base.update(code="WAIT_FEED",label="Venter på markedet",
                    severity="IDLE",
                    detail="Arbeider, men ingen ferske Tech100-kurser; "
                           "kan skyldes markedspause")
        return base
    if decision is None:
        base.update(code="WARMUP",label="Samler tekniske data",
                    severity="YELLOW",active=True,
                    detail="AI-worker og kursstrøm er aktive; ingen "
                           "fullført vurdering ennå")
        return base
    base.update(code="ACTIVE",label="AI på saken",
                severity="GREEN",active=True,
                detail="Worker og kursdata aktive; venter på "
                       "neste hendelsesstyrte modellvurdering")
    return base


def load_ai_technical_status(*,db_path="pricegauger.db",now=None):
    """Never create research schema from global status widgets."""
    with connect(db_path) as db:
        try:
            heartbeat=db.execute(
                "SELECT tick_at,key_configured,result,error_type "
                "FROM lsim_ai_technical_heartbeat WHERE worker_key=?",
                (WORKER_KEY,)).fetchone()
        except Exception:
            # Installation may not have completed. Keep status explicitly unstarted.
            heartbeat=None
        if heartbeat is None:
            return classify_ai_status(now=now)
        try:
            quote=db.execute("""
                SELECT MAX(quote_at) AS quote_at FROM lsim_hyper_quotes_1s
            """).fetchone()
            latest_quote=quote["quote_at"] if quote else None
        except Exception:
            latest_quote=None
        try:
            decision=db.execute("""
                SELECT as_of,requested_at,model_status,event_kind,target
                FROM lsim_ai_technical_decisions
                ORDER BY requested_at DESC LIMIT 1
            """).fetchone()
        except Exception:
            decision=None
    return classify_ai_status(
        heartbeat=dict(heartbeat),
        quote_at=latest_quote,
        decision=dict(decision) if decision else None,
        now=now,
    )
