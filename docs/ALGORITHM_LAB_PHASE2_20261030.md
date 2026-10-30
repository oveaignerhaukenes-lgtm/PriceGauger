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
