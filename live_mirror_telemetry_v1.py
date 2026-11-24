"""Bounded asynchronous LIVE evidence, never part of the execution authority.

Producer is nonblocking; DB I/O happens only in the telemetry thread.
Dropped events are observable, and must count as incomplete evidence.
No additional broker requests. No credentials or account balances in queue.
"""
import json
import logging
from queue import Queue, Full, Empty
from threading import Thread, Lock
from datetime import datetime, timezone
from database import connect, run_postgres_schema_once_v1

LOGGER=logging.getLogger("pricegauger.live_mirror.telemetry")
_QUEUE=Queue(maxsize=4096)
_LOCK=Lock()
_STARTED=False
_DROPPED=0


def ensure_telemetry_schema(db_path):
    def initialize():
        with connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pg_live_mirror_trace_v1(
              event_key TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
              decision_key TEXT NOT NULL, event_type TEXT NOT NULL,
              observed_at TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS pg_mirror_trace_lookup_v1
                ON pg_live_mirror_trace_v1(instance_id,decision_key,event_type)""")
    run_postgres_schema_once_v1("pg_live_mirror_trace_v1",initialize)


def _enqueue(event_key,instance_id,decision_key,event_type,payload):
    global _DROPPED
    if not _STARTED:
        return
    try:
        _QUEUE.put_nowait((str(event_key),str(instance_id),str(decision_key),
            str(event_type),datetime.now(timezone.utc).isoformat(),
            json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)))
    except (Full,ValueError,TypeError):
        _DROPPED+=1


def observe_decision(*, instance_id, decision_key, strategy_key, timeframe,
                     raw, approved, actual, action):
    """First new decision only. Producer must never raise into LIVE."""
    try:
        _enqueue("decision:"+str(decision_key),instance_id,decision_key,"DECISION",
                 dict(strategy=strategy_key,timeframe=timeframe,raw=float(raw),
                      approved=float(approved),actual=float(actual),action=str(action)))
    except Exception:
        pass


def observe_submission(*, instance_id, decision_key, request_key, side, amount,
                       action, actual, expected):
    try:
        _enqueue("submission:"+str(request_key),instance_id,decision_key,"SUBMIT",
                 dict(request_key=str(request_key),side=str(side),amount=float(amount),
                      action=str(action),actual=float(actual),expected=float(expected)))
    except Exception:
        pass


def _persist(batch,db_path):
    ensure_telemetry_schema(db_path)
    with connect(db_path) as db:
        for row in batch:
            db.execute("""INSERT INTO pg_live_mirror_trace_v1
                (event_key,instance_id,decision_key,event_type,observed_at,payload_json)
                VALUES(?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING""",row)


def _writer(db_path):
    global _DROPPED
    while True:
        first=_QUEUE.get()
        batch=[first]
        while len(batch)<128:
            try:
                batch.append(_QUEUE.get_nowait())
            except Empty:
                break
        try:
            _persist(batch,db_path)
        except Exception as exc:
            _DROPPED+=len(batch)
            LOGGER.warning("LIVE_MIRROR telemetry batch lost n=%d error=%s",len(batch),type(exc).__name__)
        if _DROPPED:
            LOGGER.warning("LIVE_MIRROR telemetry cumulative dropped=%d",_DROPPED)


def start_mirror_telemetry(*,db_path="pricegauger.db"):
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        thread=Thread(target=_writer,args=(db_path,),name="mirror-live-evidence",daemon=True)
        thread.start()
        _STARTED=True
