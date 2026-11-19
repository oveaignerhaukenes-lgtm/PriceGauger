"""Read-only provenance, data-link evidence and causal observer statistics.

Never contact Saxo, change a V3 latch, or classify stale exchange data as a
confirmed network outage. All numbers refer to persisted PriceGauger evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from database import connect


@dataclass(frozen=True, slots=True)
class ModuleDefinitionV1:
    key: str
    name: str
    source: str
    operation: str
    output: str
    mode: str
    settings: str
    page: str


MODULES_V1 = (
    ModuleDefinitionV1(
        "canonical", "Saxo 1m-priser", "Saxo stream / lagrede 1m-barer, eksakt UIC",
        "Normaliserer OHLC til kanoniske, tidsstemplede 1m-barer",
        "pg_v2_market_bars_1m", "Innsamling",
        "Instrumentabonnement i TradingDesk; ingen Saxo-kall fra denne siden",
        "pages/0_TradingDesk.py",
    ),
    ModuleDefinitionV1(
        "profile", "Markedsprofil 3×3", "61 sammenhengende fullførte 1m-barer",
        "Måler trend, rytme, retningseffektivitet og sving",
        "3×3 tilstand + observerte tall", "Analyse / observasjon",
        "60 returer; ingen interpolering; tilstandsgrenser er forskningshypoteser",
        "pages/0_Markedsmodeller.py",
    ),
    ModuleDefinitionV1(
        "observer", "Strategi × marked", "Eksakt eide/armede V3-strategier + 3×3-tilstand",
        "Lagrer observasjon ca. hvert 5. minutt; merker fremtidig pris først etter 5 fullførte barer",
        "Strategi, tilstand og 5m PRIS-proxy (ikke netto P/L)", "SHADOW · ingen ordre",
        "Fast 5m evaluering; ingen automatisk innlæring av STOPP-regler",
        "pages/0_Markedsfilter.py",
    ),
    ModuleDefinitionV1(
        "filter", "STOPP/KJØR-nødmekanisme", "Vedvarende instans/strategi-lås i PostgreSQL + V3-beslutning",
        "Veto mot OPEN/ADD både før og etter ordreservasjon",
        "KJØR/STOPP per aktiv strategi; CLOSE/REDUCE beholdes", "LIVE · kun manuelt STOPP",
        "Endres med bekreftelse under AutoTrader V3 → instans; standard KJØR",
        "pages/0_AutoTrader_V3.py",
    ),
    ModuleDefinitionV1(
        "rest", "Saxo REST-kvoter", "Eksisterende observerte LIVE GET/POST-svar og kvoteheadere",
        "Teller kall/429 per endepunkt og lagrer sikre aggregeringer",
        "Saxo-kvoter og tellinger per 15m/1t/6t/24t", "Telemetri · ingen ordre",
        "Avlesning fra Saxo-headere; ingen ekstra Saxo-kall",
        "pages/1_Saxo_OpenAPI.py",
    ),
    ModuleDefinitionV1(
        "paper", "Trade/FLAT PAPER-lab", "Kanoniske 1m-barer + simulerte handler/kostnader",
        "Tren/test av markedsformer på tidsadskilte data",
        "Hypoteser, holdout og falske blokkeringer", "Manuell PAPER · ikke LIVE",
        "Instrument, strategi, tidsvindu og kostnadsscenario velges i labben",
        "pages/0_AutoTrader_Gate_Lab.py",
    ),
)


def _date(value) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def evidence_freshness_v1(value, *, now: datetime | None = None,
                          fresh_seconds: int = 180) -> dict:
    """Data freshness, NOT a live network connectivity assertion."""
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = _date(value)
    if stamp is None:
        return {"symbol": "⚪", "label": "INGEN OBSERVASJON", "age_seconds": None}
    age = (clock - stamp).total_seconds()
    if age < -30:
        return {"symbol": "⚪", "label": "KLOKKEAVVIK", "age_seconds": round(age)}
    return {
        "symbol": "🟢" if age <= fresh_seconds else "🟠",
        "label": "NYLIGE DATA" if age <= fresh_seconds else "INGEN NYE DATA",
        "age_seconds": max(0, round(age)),
    }


def latest_observed_timestamp_v1(values) -> datetime | None:
    """Compare mixed timestamp representations by UTC time, never text order."""
    valid = (_date(value) for value in values)
    return max((stamp for stamp in valid if stamp is not None), default=None)


def _missing_table(exc: Exception, table: str) -> bool:
    message = str(exc).lower()
    return "no such table" in message or (
        "does not exist" in message and table.lower() in message)


def _optional_rows(db_path, table: str, sql: str, params=()) -> tuple | None:
    try:
        with connect(db_path) as db:
            return tuple(dict(row) for row in db.execute(sql, params).fetchall())
    except Exception as exc:
        if _missing_table(exc, table):
            return None
        raise


def _where_ids(items) -> tuple[str, tuple]:
    values = tuple(dict.fromkeys(items))
    return ",".join("?" for _ in values), values


def load_market_filter_evidence_v1(*, instance_ids=(), instrument_ids=(),
                                   account_ids=(), hours: int = 24,
                                   db_path="pricegauger.db", now=None) -> dict:
    """Bounded read of real module sources, never a Saxo or LIVE control call."""
    instance_ids = tuple(instance_ids)
    instrument_ids = tuple(instrument_ids)
    account_ids = tuple(account_ids)
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    span = max(1, min(int(hours), 7 * 24))
    since = (clock - timedelta(hours=span)).isoformat()
    observations = _optional_rows(
        db_path, "pg_v3_state_strategy_observations_v1",
        """SELECT COUNT(*) AS total,
            SUM(CASE WHEN future_5m_completed_at IS NOT NULL THEN 1 ELSE 0 END) AS matured,
            MAX(observed_as_of) AS newest,
            MAX(future_5m_completed_at) AS newest_matured
            FROM pg_v3_state_strategy_observations_v1
            WHERE observed_as_of>=?""", (since,),
    )
    by_profile = _optional_rows(
        db_path, "pg_v3_state_strategy_observations_v1",
        """SELECT strategy_key,state_key,COUNT(*) AS samples,
            SUM(CASE WHEN future_5m_completed_at IS NOT NULL THEN 1 ELSE 0 END) AS matured,
            AVG(future_5m_price_return_pct) AS mean_future_price_pct
            FROM pg_v3_state_strategy_observations_v1
            WHERE observed_as_of>=?
            GROUP BY strategy_key,state_key ORDER BY samples DESC LIMIT 100""", (since,),
    )
    by_instance = _optional_rows(
        db_path, "pg_v3_state_strategy_observations_v1",
        """SELECT instance_id,MAX(observed_as_of) AS newest,
            COUNT(*) AS samples,
            SUM(CASE WHEN future_5m_completed_at IS NOT NULL THEN 1 ELSE 0 END) AS matured
            FROM pg_v3_state_strategy_observations_v1
            WHERE observed_as_of>=? GROUP BY instance_id""", (since,),
    )
    latest_profiles = _optional_rows(
        db_path, "pg_v3_state_strategy_observations_v1",
        """SELECT instance_id,observed_as_of,state_key,efficiency,
            direction_changes,volatility_pct_1m,rhythm_evidence
            FROM pg_v3_state_strategy_observations_v1
            WHERE observed_as_of>=?
            ORDER BY observed_as_of DESC LIMIT 500""", (since,),
    )
    bar_rows = ()
    if instrument_ids:
        placeholders, values = _where_ids(int(v) for v in instrument_ids)
        bar_rows = _optional_rows(
            db_path, "pg_v2_market_bars_1m",
            f"""SELECT instrument_id,MAX(bar_time) AS newest
                FROM pg_v2_market_bars_1m WHERE instrument_id IN ({placeholders})
                GROUP BY instrument_id""", values,
        )
    runtime_rows = ()
    if instance_ids:
        placeholders, values = _where_ids(instance_ids)
        runtime_rows = _optional_rows(
            db_path, "autotrader_v3_live_runtime_state",
            f"""SELECT trader_id,status,updated_at FROM autotrader_v3_live_runtime_state
                WHERE trader_id IN ({placeholders})""", values,
        )
    account_rows = ()
    if account_ids:
        placeholders, values = _where_ids(account_ids)
        account_rows = _optional_rows(
            db_path, "pg_saxo_account_truth_v1",
            f"""SELECT account_id,account_name,observed_at
                FROM pg_saxo_account_truth_v1 WHERE account_id IN ({placeholders})
                ORDER BY observed_at DESC LIMIT 500""", values,
        )
    rest_rows = _optional_rows(
        db_path, "pg_saxo_rest_usage_windows_v1",
        """SELECT MAX(window_ended_at) AS newest, SUM(call_count) AS calls
            FROM pg_saxo_rest_usage_windows_v1 WHERE window_ended_at>=?""",
        ((clock - timedelta(minutes=15)).isoformat(),),
    )
    stream_rows = _optional_rows(
        db_path, "realtime_stream_status",
        """SELECT market,updated_at,state FROM realtime_stream_status
            ORDER BY updated_at DESC LIMIT 50""",
    )
    sample = observations[0] if observations else {}
    latest_by_instance = {}
    for item in (latest_profiles or ()):
        latest_by_instance.setdefault(str(item["instance_id"]), item)
    return {
        "observer_table_present": observations is not None,
        "total": int(sample.get("total") or 0),
        "matured": int(sample.get("matured") or 0),
        "last_observed": sample.get("newest"),
        "last_matured": sample.get("newest_matured"),
        "profiles": by_profile or (),
        "instances": {str(r["instance_id"]): r for r in (by_instance or ())},
        "latest_profiles": latest_by_instance,
        "bars": {int(r["instrument_id"]): r.get("newest") for r in (bar_rows or ())},
        "runtime": {str(r["trader_id"]): r for r in (runtime_rows or ())},
        "account_names": {
            str(r["account_id"]): str(r["account_name"])
            for r in reversed(account_rows or ()) if r.get("account_name")
        },
        "rest_table_present": rest_rows is not None,
        "rest_last": rest_rows[0].get("newest") if rest_rows else None,
        "rest_calls_15m": int(rest_rows[0].get("calls") or 0) if rest_rows else 0,
        "stream_table_present": stream_rows is not None,
        "streams": {str(r["market"]): r for r in (stream_rows or ())},
        "stream_last": latest_observed_timestamp_v1(
            r.get("updated_at") for r in (stream_rows or ())),
    }


__all__ = ["ModuleDefinitionV1", "MODULES_V1", "evidence_freshness_v1",
           "latest_observed_timestamp_v1",
           "load_market_filter_evidence_v1"]
