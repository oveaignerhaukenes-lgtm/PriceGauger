"""Client for a dedicated, separately hosted Algorithm Lab Python sandbox.

Web only sends selected public OHLC and model code to an explicitly configured
HTTPS endpoint. No Saxo credentials, database URLs, account IDs or auth tokens
are forwarded (except the sandbox's dedicated shared credential).
"""
from __future__ import annotations

import os
from typing import Sequence
from urllib.parse import urlsplit
import requests

from algorithm_lab_sandbox_v2 import MAX_SCRIPT_BARS, validate_script
from algorithm_lab_v1 import utc


def remote_ready(env=None) -> bool:
    e = os.environ if env is None else env
    base = str(e.get("ALGORITHM_LAB_SANDBOX_URL") or "").strip().rstrip("/")
    secret = str(e.get("ALGORITHM_LAB_SANDBOX_TOKEN") or "").strip()
    try:
        loc = urlsplit(base)
        is_local = loc.scheme == "http" and loc.hostname in ("localhost", "127.0.0.1")
        return bool(len(secret) >= 32 and
                    (loc.scheme == "https" or is_local) and loc.hostname and
                    not loc.username and not loc.password and
                    not loc.query and not loc.fragment and
                    not loc.path.strip("/"))
    except ValueError:
        return False


def run_remote_python(*, code: str, bars: Sequence, env=None,
                      post=requests.post) -> tuple[int, ...]:
    e = os.environ if env is None else env
    if not remote_ready(e):
        raise RuntimeError("Frittstående Python-sandbox er ikke konfigurert.")
    if not 1 <= len(bars) <= MAX_SCRIPT_BARS:
        raise ValueError("Python-forskning krever 1–1500 1m-barer.")
    observations = []
    previous = None
    from datetime import timedelta
    for row in bars:
        t = utc(row.bar_time)
        if previous is not None and t-previous != timedelta(minutes=1):
            raise ValueError("Historiske 1m-data har hull. Del opp testperioden.")
        item = {"at": t.isoformat()}
        for field in ("open","high","low","close"):
            value = float(getattr(row,field))
            if not 0 < value < 1e12:
                raise ValueError("Ugyldige historiske priser.")
            item[field] = value
        observations.append(item)
        previous = t
    url = e["ALGORITHM_LAB_SANDBOX_URL"].strip().rstrip("/") + "/v1/execute"
    try:
        response = post(
            url,
            headers={"X-Algorithm-Lab-Key": e["ALGORITHM_LAB_SANDBOX_TOKEN"],
                     "Content-Type": "application/json"},
            json={"code":validate_script(code),"bars":observations},
            timeout=90, allow_redirects=False)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        raise RuntimeError("Separat Python-sandbox svarte ikke eller avviste forespørselen.") from None
    if (not isinstance(data,dict) or set(data) != {"directions"} or
            not isinstance(data["directions"],list) or
            len(data["directions"]) != len(observations) or
            any(type(v) is not int or v not in (-1,0,1)
                for v in data["directions"])):
        raise RuntimeError("Python-sandbox returnerte uventede resultater.")
    return tuple(data["directions"])


__all__ = ["remote_ready","run_remote_python"]
