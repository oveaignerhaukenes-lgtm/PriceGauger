from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from database import connect, database_config_status, database_url


@dataclass(frozen=True, slots=True)
class TableDiagnostic:
    table: str
    count: int | None
    latest: str
    status: str
    error: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticReport:
    backend: str
    source: str
    runtime: str
    database_fingerprint: str
    tables: tuple[TableDiagnostic, ...]
    decision_markets: tuple[str, ...]
    diagnosis: tuple[str, ...]


_TABLES: tuple[tuple[str, str], ...] = (
    ("telegram_flow_posts", "published_at"),
    ("telegram_flow_snapshots", "as_of"),
    ("information_state_snapshots", "as_of"),
    ("decision_state_snapshots", "as_of"),
    ("market_mover_alerts", "updated_at"),
    ("overview_summaries", "as_of"),
)


def _safe_fingerprint() -> str:
    value = database_url().strip()
    if not value:
        return "sqlite-local"
    parsed = urlparse(value)
    identity = f"{parsed.hostname or ''}:{parsed.port or ''}/{parsed.path.lstrip('/')}"
    digest = sha256(identity.encode("utf-8")).hexdigest()[:10]
    host = parsed.hostname or "unknown-host"
    database = parsed.path.lstrip("/") or "unknown-db"
    return f"{host}/{database} · {digest}"


def _table_diagnostic(db_path: str | Path, table: str, latest_column: str) -> TableDiagnostic:
    try:
        with connect(db_path) as db:
            row = db.execute(
                f"SELECT COUNT(*) AS count, MAX({latest_column}) AS latest FROM {table}"
            ).fetchone()
        return TableDiagnostic(
            table=table,
            count=int(row["count"]),
            latest=str(row["latest"] or ""),
            status="OK",
        )
    except Exception as exc:
        return TableDiagnostic(
            table=table,
            count=None,
            latest="",
            status="ERROR",
            error=f"{exc.__class__.__name__}: {exc}",
        )


def _decision_markets(db_path: str | Path) -> tuple[str, ...]:
    try:
        with connect(db_path) as db:
            rows = db.execute(
                "SELECT DISTINCT market FROM decision_state_snapshots ORDER BY market"
            ).fetchall()
        return tuple(str(row["market"]) for row in rows)
    except Exception:
        return ()


def build_runtime_diagnostic_report(
    db_path: str | Path = "pricegauger.db",
) -> RuntimeDiagnosticReport:
    config = database_config_status()
    tables = tuple(
        _table_diagnostic(db_path, table, latest_column)
        for table, latest_column in _TABLES
    )
    by_name = {item.table: item for item in tables}
    markets = _decision_markets(db_path)
    diagnosis: list[str] = []

    flow_posts = by_name["telegram_flow_posts"]
    flow_snapshots = by_name["telegram_flow_snapshots"]
    information = by_name["information_state_snapshots"]
    decisions = by_name["decision_state_snapshots"]

    if any(item.status == "ERROR" for item in tables):
        failed = ", ".join(item.table for item in tables if item.status == "ERROR")
        diagnosis.append(f"Database query failed for: {failed}.")
    if (flow_posts.count or 0) > 0 and (flow_snapshots.count or 0) == 0:
        diagnosis.append("Telegram posts exist, but no Telegram Flow snapshot exists.")
    if (flow_snapshots.count or 0) > 0 and (information.count or 0) == 0:
        diagnosis.append("Telegram Flow exists, but Information State has not been persisted.")
    if (information.count or 0) > 0 and (decisions.count or 0) == 0:
        diagnosis.append("Information State exists, but Decision State bootstrap has not completed.")
    if (decisions.count or 0) > 0 and len(markets) < 5:
        diagnosis.append(
            f"Decision State is incomplete: {len(markets)} markets present ({', '.join(markets) or 'none'})."
        )
    if not diagnosis:
        diagnosis.append("The persisted Telegram → Information State → Decision State chain is complete.")

    return RuntimeDiagnosticReport(
        backend=str(config.get("backend") or "unknown"),
        source=str(config.get("source") or "unknown"),
        runtime=str(config.get("runtime") or "unknown"),
        database_fingerprint=_safe_fingerprint(),
        tables=tables,
        decision_markets=markets,
        diagnosis=tuple(diagnosis),
    )
