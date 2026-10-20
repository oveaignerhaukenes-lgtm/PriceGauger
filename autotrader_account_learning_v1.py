"""Account-specific, durable V3 learning observer — never an execution engine.

Follows an explicitly selected Saxo account. Correlates verified five-minute
broker equity observations with the as-of strategy and RECONCILED V3 orders.
Generates reproducible *research hypotheses* for SIM A/B evaluation, NOT
broker-profit assertions or automatic changes to running strategies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import isfinite
import json
from typing import Mapping, Sequence

from database import connect
from autotrader_saxo_account_truth_v1 import (
    ensure_account_truth_schema_v1, load_account_truth_v1,
)
from autotrader_saxo_strategy_timeline_v1 import (
    ObservedLiveNAVWindowV1, observed_live_nav_windows_v1,
)

MAX_FINDINGS=150
LOOKBACK_DAYS=14
MAX_EXECUTIONS=1500
MAX_WINDOW_AGE_MINUTES=45
MIN_WINDOW_SAMPLES=4
MIN_WINDOW_MINUTES=15
LOSS_THRESHOLD_PCT=-0.25


def utc(value:datetime | str)->datetime:
    parsed=(value if isinstance(value,datetime) else
            datetime.fromisoformat(str(value).replace("Z","+00:00")))
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def ensure_account_learning_schema_v1(*,db_path="pricegauger.db")->None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_account_learning_watches_v1(
            account_id TEXT PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS pg_account_learning_findings_v1(
            finding_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            strategy_key TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            market TEXT NOT NULL,
            first_observed TEXT NOT NULL,
            last_observed TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            test_plan TEXT NOT NULL,
            confidence_scope TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS pg_learning_findings_account_time_v1
            ON pg_account_learning_findings_v1(account_id,last_observed DESC)""")


def set_account_learning_watch_v1(*,account_id:str,enabled:bool,
                                  db_path="pricegauger.db")->None:
    account=str(account_id or "").strip()
    if not account:
        raise ValueError("exact Saxo account_id required")
    if not isinstance(enabled,bool):
        raise ValueError("enabled must be boolean")
    ensure_account_truth_schema_v1(db_path=db_path)
    ensure_account_learning_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        known=db.execute("""SELECT 1 FROM pg_saxo_account_truth_v1
            WHERE account_id=? LIMIT 1""",(account,)).fetchone()
        if known is None:
            raise ValueError("select an observed Saxo account, not a hypothetical account")
        now=datetime.now(timezone.utc).isoformat()
        db.execute("""INSERT INTO pg_account_learning_watches_v1
            (account_id,enabled,created_at,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE
            SET enabled=excluded.enabled,updated_at=excluded.updated_at""",
            (account,enabled,now,now))


def load_account_learning_watches_v1(*,db_path="pricegauger.db")->tuple[dict,...]:
    ensure_account_learning_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT account_id,enabled,created_at,updated_at
            FROM pg_account_learning_watches_v1 ORDER BY account_id""").fetchall()
    return tuple(dict(row) for row in rows)


def load_account_learning_findings_v1(*,account_id:str,limit:int=80,
                                      db_path="pricegauger.db")->tuple[dict,...]:
    if not account_id:
        raise ValueError("account scope required")
    ensure_account_learning_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        rows=db.execute("""SELECT finding_id,account_id,instance_id,strategy_key,
            timeframe,market,first_observed,last_observed,kind,status,title,
            hypothesis,test_plan,confidence_scope,evidence_json,created_at
            FROM pg_account_learning_findings_v1
            WHERE account_id=? ORDER BY last_observed DESC,created_at DESC
            LIMIT ?""",(account_id,max(1,min(MAX_FINDINGS,int(limit))))).fetchall()
    return tuple(dict(row) for row in rows)


def load_account_learning_executions_v1(*,account_id:str,since:datetime,
                                        db_path="pricegauger.db") -> tuple[dict,...] | None:
    """None means the audit table was unavailable: never mistake it for zero trades."""
    try:
        with connect(db_path) as db:
            rows=db.execute("""SELECT request_key,account_id,instance_id,
                market_name,action,side,direction,amount,inventory_before,
                inventory_after,executed_at
                FROM autotrader_v3_execution_events
                WHERE account_id=? AND executed_at>=?
                ORDER BY executed_at DESC LIMIT ?""",
                (account_id,utc(since),MAX_EXECUTIONS)).fetchall()
        return tuple(dict(x) for x in reversed(rows))
    except Exception:
        return None


@dataclass(frozen=True,slots=True)
class AccountLearningCandidateV1:
    finding_id:str
    account_id:str
    instance_id:str
    strategy_key:str
    timeframe:str
    market:str
    first_observed:str
    last_observed:str
    kind:str
    status:str
    title:str
    hypothesis:str
    test_plan:str
    confidence_scope:str
    evidence_json:str


def propose_account_learning_v1(*,account_id:str,
    samples:Sequence[Mapping], executions:Sequence[Mapping] | None,
    now:datetime|None=None)->tuple[AccountLearningCandidateV1,...]:
    """Pure as-of hypotheses; neither train on future observations nor mix accounts."""
    clock=utc(now or datetime.now(timezone.utc))
    if any(str(row.get("account_id")) != account_id for row in samples):
        raise ValueError("cross-account NAV evidence rejected")
    if executions is not None and any(
        str(row.get("account_id")) != account_id for row in executions
    ):
        raise ValueError("cross-account execution evidence rejected")
    windows=observed_live_nav_windows_v1(samples)
    result=[]
    for window in windows:
        if (window.observations<MIN_WINDOW_SAMPLES or
            window.value_change_pct is None or
            (window.last_observed-window.first_observed).total_seconds()
                < MIN_WINDOW_MINUTES*60):
            continue
        age=(clock-window.last_observed).total_seconds()
        if age<0 or age>MAX_WINDOW_AGE_MINUTES*60:
            continue
        if not isfinite(window.value_change_pct):
            continue
        # No hypothesis about an unfunded (or unreliable) account.
        if window.first_value<=0 or window.last_value<=0:
            continue

        matching=[]
        if executions is not None:
            for event in executions:
                try:
                    when=utc(event["executed_at"])
                except (ValueError,TypeError,KeyError):
                    continue
                if (window.first_observed<=when<=window.last_observed and
                    str(event.get("instance_id"))==window.instance_id):
                    matching.append(event)
        exits=sum(1 for e in matching if str(e.get("action","")).upper()
                  in ("CLOSE","REVERSE","REDUCE"))
        entries=sum(1 for e in matching if str(e.get("action","")).upper()
                    in ("OPEN","ADD","REVERSE"))
        # This is account NAV change. Never call it net profit.
        observed_decline=window.value_change_pct<=LOSS_THRESHOLD_PCT
        high_turnover=len(matching)>=4 and exits>=2 and entries>=2
        if observed_decline and high_turnover and executions is not None:
            kind="TEST_PRICE_CONFIRMED_ANTI_CHURN"
            title="Undersøk whipsaw ved uavstemt NAV-fall"
            hypothesis=(
                "Flere bekreftede V3-ordre opptrer i samme observerte "
                "strategivindu som fallende Saxo-kontoverdi. Test om "
                "prisbekreftelse / cooldown reduserer churn, uten å "
                "anta at NAV-endringen er handelstap."
            )
            plan=(
                "SIM A/B: identiske historiske UTC-barer, spredd/kostnader "
                "og samme størrelse; baseline mot prisbekreftet inngang "
                "og 1–2 ferdige barers cooldown. Sammenlign nettoavkastning, "
                "drawdown, antall handler og out-of-sample perioder. "
                "Avstem Saxo cashflows før LIVE-konklusjon."
            )
        elif observed_decline:
            kind="RECONCILE_NAV_BEFORE_TUNING"
            title="Avstem kontoendring før strategitilpasning"
            hypothesis=(
                "Kontoverdien falt i et entydig observert LIVE-strategivindu, "
                "men verifisert strategi-P/L er ukjent. Andre handler, "
                "inn-/utbetalinger, finansiering og FX kan forklare endringen."
            )
            plan=(
                "Innhent kontospesifikke Saxo-transaksjoner og dagsresultat; "
                "avstem overføringer, finansiering, kostnader og manualhandel. "
                "Utsett optimalisering til eventuelle reelle nettotap er bekreftet."
            )
        elif high_turnover and executions is not None:
            kind="TEST_COST_AWARE_HOLD"
            title="Test kostnadsfølsomhet ved mange handler"
            hypothesis=(
                "Flere V3-ordre er bekreftet i samme strategi-/kontovindu. "
                "Dette er en turnover-observasjon, ikke bevis på lav avkastning."
            )
            plan=(
                "SIM A/B med identiske markedsbarer og kostnadsantakelser: "
                "baseline mot svak momentumdeadband eller cooldown. "
                "Forkast forslaget hvis nettoresultatet forverres out-of-sample."
            )
        else:
            continue
        evidence={
            "account_id":account_id,"instance_id":window.instance_id,
            "strategy":window.strategy_key,"timeframe":window.timeframe,
            "market":window.market,"currency":window.currency,
            "first_observed":window.first_observed.isoformat(),
            "last_observed":window.last_observed.isoformat(),
            "verified_nav_samples":window.observations,
            "saxo_total_value_start":window.first_value,
            "saxo_total_value_end":window.last_value,
            "nav_change_unadjusted":window.value_change,
            "nav_change_pct_unadjusted":window.value_change_pct,
            "max_observed_drawdown_pct":window.max_observed_drawdown_pct,
            "confirmed_v3_orders":len(matching) if executions is not None else None,
            "confirmed_v3_entries":entries if executions is not None else None,
            "confirmed_v3_exits":exits if executions is not None else None,
            "execution_ledger_available":executions is not None,
            "verified_strategy_net_pnl":None,
            "cashflows_reconciled":False,
            "manual_trades_excluded":False,
        }
        # A window has a stable identity, so 5m collection never spams copies.
        identity="|".join((account_id,window.instance_id,window.strategy_key,
                           window.first_observed.isoformat(),kind))
        fid=sha256(identity.encode("utf-8")).hexdigest()
        result.append(AccountLearningCandidateV1(
            finding_id=fid,account_id=account_id,instance_id=window.instance_id,
            strategy_key=window.strategy_key,timeframe=window.timeframe,
            market=window.market,
            first_observed=window.first_observed.isoformat(),
            last_observed=window.last_observed.isoformat(),
            kind=kind,status="RESEARCH_ONLY",title=title,
            hypothesis=hypothesis,test_plan=plan,
            confidence_scope="OBSERVATIONAL_NAV_NOT_STRATEGY_PNL",
            evidence_json=json.dumps(evidence,sort_keys=True,allow_nan=False),
        ))
    return tuple(result)


def run_account_learning_cycle_v1(*,db_path="pricegauger.db",
                                  now:datetime|None=None)->dict[str,int]:
    """Five-minute sidecar. Reads durable telemetry; writes only research rows."""
    ensure_account_learning_schema_v1(db_path=db_path)
    accounts=[str(x["account_id"]) for x in load_account_learning_watches_v1(
        db_path=db_path) if bool(x["enabled"])]
    observed=proposals=inserted=errors=0
    for account in accounts:
        try:
            samples=load_account_truth_v1(
                account_id=account,days=LOOKBACK_DAYS,db_path=db_path)
            observed+=len(samples)
            if not samples:
                continue
            earliest=min(utc(x["observed_at"]) for x in samples)
            events=load_account_learning_executions_v1(
                account_id=account,since=earliest,db_path=db_path)
            candidates=propose_account_learning_v1(
                account_id=account,samples=samples,executions=events,now=now)
            proposals+=len(candidates)
            for c in candidates:
                with connect(db_path) as db:
                    mark=datetime.now(timezone.utc).isoformat()
                    result=db.execute("""INSERT INTO pg_account_learning_findings_v1(
                        finding_id,account_id,instance_id,strategy_key,timeframe,
                        market,first_observed,last_observed,kind,status,title,
                        hypothesis,test_plan,confidence_scope,evidence_json,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(finding_id) DO NOTHING""",
                        (*tuple(asdict(c).values()),mark))
                    inserted+=int(result.rowcount==1)
        except Exception:
            # One account's stale/invalid history cannot affect other accounts
            # or interfere with Saxo execution.
            errors+=1
    return {"watched_accounts":len(accounts),"samples":observed,
            "proposals":proposals,"new_findings":inserted,"errors":errors}


__all__=[
    "AccountLearningCandidateV1","ensure_account_learning_schema_v1",
    "set_account_learning_watch_v1","load_account_learning_watches_v1",
    "load_account_learning_findings_v1","load_account_learning_executions_v1",
    "propose_account_learning_v1","run_account_learning_cycle_v1",
]
