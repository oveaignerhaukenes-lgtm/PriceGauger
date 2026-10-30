"""Separate credential-free Algorithm Lab FastAPI sandbox service.

Run only on a dedicated Docker host with no PG Database/Saxo/OpenAI
credentials. Require transport TLS + firewall restrictions outside the app.
Never mount host Docker socket into the PriceGauger web/worker container.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from hmac import compare_digest
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from algorithm_lab_sandbox_v2 import (
    MAX_SCRIPT_BARS, execute_in_isolated_container, standalone_worker_ready,
    validate_script,
)

app = FastAPI(title="PriceGauger Research Sandbox", docs_url=None, redoc_url=None)
MAX_BODY = 240000


@app.get("/healthz")
def healthz():
    return {"ready": bool(standalone_worker_ready() and
                          len(os.getenv("ALGORITHM_LAB_SANDBOX_TOKEN","")) >=32)}


@app.post("/v1/execute")
async def execute(request: Request) -> dict:
    credential = os.getenv("ALGORITHM_LAB_SANDBOX_TOKEN","")
    observed = request.headers.get("X-Algorithm-Lab-Key","")
    if len(credential)<32 or not compare_digest(observed,credential):
        raise HTTPException(401, "unauthorized")
    if not standalone_worker_ready():
        raise HTTPException(503, "sandbox not ready")
    if request.headers.get("content-length") and int(request.headers["content-length"]) > MAX_BODY:
        raise HTTPException(413, "too large")
    raw = await request.body()
    if len(raw)>MAX_BODY:
        raise HTTPException(413, "too large")
    import json
    try:
        payload = json.loads(raw)
        if not isinstance(payload,dict) or set(payload)!={"code","bars"}:
            raise ValueError("invalid input envelope")
        code = validate_script(payload["code"])
        values = payload["bars"]
        if not isinstance(values,list) or not 1<=len(values)<=MAX_SCRIPT_BARS:
            raise ValueError("invalid bar count")
        from types import SimpleNamespace
        rows = []
        for point in values:
            if not isinstance(point,dict) or set(point)!={"at","open","high","low","close"}:
                raise ValueError("invalid bar schema")
            rows.append(SimpleNamespace(
                bar_time=point["at"],open=point["open"],high=point["high"],
                low=point["low"],close=point["close"]))
    except (ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(422, "invalid dataset or code")
    try:
        results = execute_in_isolated_container(
            code=code, bars=rows, timeout_per_bar=0.15)
    except (ValueError, RuntimeError, TimeoutError, OSError):
        raise HTTPException(422, "isolated execution rejected")
    return {"directions":list(results)}


__all__=["app"]
