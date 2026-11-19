"""Minimal V4 status endpoint. Not a trading control plane.

This prototype intentionally cannot authenticate to Saxo, submit orders,
change arming, ingest production credentials or modify live account state.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="AutoTrader V4 staging",
    description="Read-only local architecture bootstrap — broker disconnected.",
    version="0.0.1",
    docs_url=None,
    redoc_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "mode": "READ_ONLY", "broker": "DISCONNECTED"}


@app.get("/api/v1/status")
def status() -> dict[str, str | bool]:
    return {
        "mode": "READ_ONLY",
        "saxo_connected": False,
        "can_place_orders": False,
        "execution_enabled": False,
        "database_migrations_applied": False,
    }
