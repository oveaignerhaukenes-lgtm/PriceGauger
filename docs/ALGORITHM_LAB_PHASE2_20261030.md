# Algorithm Lab phase 2

Research-only extension, no changes to LIVE order routes or production worker.

## Components
- algorithm_lab_catalog_v2.py: allowlisted historical market and context sources. As-of timestamps for macro and news context. Account data intentionally unavailable to AI without an account permission boundary.
- algorithm_lab_versions_v2.py: immutable, database-backed experiments organized by a saved high-entropy research key. The key is not stored in the database. Users must retain their key.
- algorithm_lab_sandbox_v2.py: opt-in standalone Docker runner for Python strategies. It refuses to run if production credentials or Railway identity are present. UI does not execute arbitrary Python in web/worker.
- algorithm_lab_python_ai_v2.py: AI creates a decide(bar,state) function.
- algorithm_lab_python_replay_v2.py: PAPER next-bar accounting for sandbox decisions.
- Algorithm Lab UI includes indicative current Saxo GET cost calibration, separate annual funding assumptions, and chronological train/test split.

## Remaining deployment prerequisites
The dedicated Docker sandbox needs a separately provisioned credential-free execution host and authentication/proxy before the web UI can use it. Do not mount the Docker socket into PriceGauger web or worker.
FX based on present broker price-to-NOK conversion is not a historical FX path. Financing rates are user-provided scenarios, not verified historical Saxo funding charges. Out-of-sample is a chronological split, not automatic model optimization.

## Dedicated Python research runner

A separate host with rootless Docker can run:

```bash
export ALGORITHM_LAB_DEDICATED_SANDBOX=yes
export ALGORITHM_LAB_SANDBOX_TOKEN='<separate random 32+ char token>'
uvicorn algorithm_lab_sandbox_service_v2:app --host 127.0.0.1 --port 8341
```

This host must NOT have Railway, DATABASE_URL, Saxo, OpenAI, host broker tokens or the PriceGauger Docker socket mounted into the sandbox container. The Docker image `python:3.12.7-slim` must be pre-pulled; requests do not pull images. Put TLS and request-rate limits in front of the service, and permit only the PG web service to reach it. For web, set `ALGORITHM_LAB_SANDBOX_URL` to the HTTPS endpoint and `ALGORITHM_LAB_SANDBOX_TOKEN` to that same dedicated research token. PG sends only selected, recorded 1m OHLC and as-of numeric macro/news counts. The script only receives one observed bar at a time.

The sandbox requires an independent host/service; it is deliberately disabled in ordinary Railway web/worker environments. Do not enable the local Docker execution switch on a host that has production secrets.

## Historical FX and financing

An optional exact-UIC direct NOK Saxo FxSpot series (e.g. USDNOK) can be used for as-of conversion of the paper point value. The selected NOK point value is assumed to correspond to the starting FX rate. Bad or older-than-five-minute FX bars cause a replay failure; no fabricated rates. Confirm the instrument's quote currency explicitly. This is a historical FX conversion *scenario*, not broker cash ledger reconciliation.

Financial assumptions remain user-selected long/short annual financing charges applied only over sampled position time; they are not an exact financing invoice. Live Saxo GET calibration is from currently indicative instrument/FX/spread/fee evidence, not historical fills.

## Access and experiment metadata

The new app version archive stores allowlisted plan, timestamp, product UIC, simulated NAV summary, funding assumptions and optional FX source UIC. A generated high-entropy research key is needed to read or save archive entries. It is not a Saxo account credential, and losing it makes saved experiments inaccessible. Account data are excluded from model prompts and Python execution. Browser-based research keys require no shared user login, but a proper access-control layer is still needed before general multiuser release.
