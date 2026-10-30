"""Opt-in standalone Docker execution boundary for user/AI-authored Python.

Must run ONLY on an independent research host/worker without PostgreSQL,
Saxo, Railway or OpenAI credentials. The PG web server is deliberately
not allowed to spawn arbitrary Python. Never passes a future bar to model.
"""
from __future__ import annotations

from datetime import timedelta
import json
import os
import select
import shutil
import subprocess
from typing import Sequence

from algorithm_lab_v1 import utc

MAX_SCRIPT_BYTES = 12000
MAX_SCRIPT_BARS = 1500
IMAGE = "python:3.12.7-slim"
RUNNER = """
import json,sys
meta=json.loads(sys.stdin.readline())
src=meta['code']
ns={'__name__':'__algorithm__'}
exec(compile(src,'<research>','exec'),ns,ns)
fn=ns.get('decide')
if not callable(fn):
    raise RuntimeError('Python code must define decide(bar,state)')
state={}
for raw in sys.stdin:
    point=json.loads(raw)
    try:
        choice=fn(point,state)
        if type(choice) is not int or choice not in (-1,0,1):
            raise ValueError('decide must return -1/0/1 as int')
        sys.stdout.write(json.dumps({'signal':choice})+'\\n')
        sys.stdout.flush()
    except BaseException as exc:
        sys.stdout.write(json.dumps({'error':type(exc).__name__})+'\\n')
        sys.stdout.flush()
"""


def standalone_worker_ready(env=None, *, docker_binary=None) -> bool:
    e = os.environ if env is None else env
    # Never allow PG web/worker to turn Docker into a production secret escape.
    blocked = ("DATABASE_URL", "DATABASE_PUBLIC_URL",
               "SAXO_ACCESS_TOKEN", "SAXO_CLIENT_SECRET", "OPENAI_API_KEY",
               "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID")
    return (e.get("ALGORITHM_LAB_DEDICATED_SANDBOX") == "yes"
            and all(not e.get(name) for name in blocked)
            and (docker_binary is not None or shutil.which("docker") is not None))


def build_docker_command(*, docker_binary="docker") -> tuple[str, ...]:
    return (
        docker_binary, "run", "--rm", "-i", "--pull", "never",
        "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "32", "--memory", "128m", "--cpus", "0.5",
        "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m",
        "--workdir", "/tmp",
        IMAGE, "python", "-I", "-B", "-c", RUNNER,
    )


def validate_script(code: str) -> str:
    text = str(code or "")
    if not text.strip() or len(text.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ValueError("Python research script empty or too large.")
    # This is merely a size check. Isolation is provided by the dedicated
    # OS-level container boundary, NOT by this validation.
    return text


def execute_in_isolated_container(*, code: str, bars: Sequence,
                                  env=None, docker_binary=None,
                                  timeout_per_bar=0.5) -> tuple[int, ...]:
    """Stream bars causally: no future observations sent to research script.

    Returns only signed directions. No LIVE brokerage, database or filesystem
    access is passed through. Requires a separately provisioned Docker host.
    """
    script = validate_script(code)
    binary = docker_binary or shutil.which("docker")
    if not standalone_worker_ready(env=env, docker_binary=binary):
        raise RuntimeError("Dedicated credential-free Docker sandbox is not configured.")
    if not 1 <= len(bars) <= MAX_SCRIPT_BARS:
        raise ValueError("Choose 1 to 1500 contiguous historical bars for Python research.")
    previous = None
    payload = []
    for bar in bars:
        t = utc(bar.bar_time)
        if previous and t-previous != timedelta(minutes=1):
            raise ValueError("Python sample requires contiguous 1m candles; split gaps first.")
        fields = {"at": t.isoformat()}
        for key in ("open", "high", "low", "close"):
            value = float(getattr(bar, key))
            if not (0 < value < 1e12):
                raise ValueError("Invalid OHLC in script data.")
            fields[key] = value
        for feature in ("macro_count", "news_post_count"):
            if hasattr(bar, feature):
                val = getattr(bar, feature)
                if type(val) is not int or not -1 <= val <= 100000:
                    raise ValueError("Invalid as-of context feature.")
                fields[feature] = val
        payload.append(fields)
        previous = t
    proc = subprocess.Popen(
        build_docker_command(docker_binary=binary),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding="utf-8", bufsize=1,
        env={"PATH": os.path.dirname(binary) or "/usr/bin:/bin"},
        cwd="/", close_fds=True,
    )
    result = []
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps({"code": script}) + "\n")
        proc.stdin.flush()
        for point in payload:
            proc.stdin.write(json.dumps(point, allow_nan=False) + "\n")
            proc.stdin.flush()
            ready, _, _ = select.select([proc.stdout], [], [], timeout_per_bar)
            if not ready:
                raise TimeoutError("Sandbox model exceeded per-bar deadline.")
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("Sandbox stopped before all decisions.")
            obj = json.loads(line)
            if set(obj) != {"signal"} or type(obj["signal"]) is not int or obj["signal"] not in (-1,0,1):
                raise ValueError("Sandbox model rejected a bar or returned invalid direction.")
            result.append(obj["signal"])
        proc.stdin.close()
        proc.wait(timeout=2)
        if proc.returncode:
            raise RuntimeError("Sandbox process finished with an error.")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
    return tuple(result)


__all__ = ["standalone_worker_ready", "build_docker_command", "validate_script",
           "execute_in_isolated_container"]
