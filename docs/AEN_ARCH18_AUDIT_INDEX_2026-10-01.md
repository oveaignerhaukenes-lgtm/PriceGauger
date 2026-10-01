# PriceGauger architecture audit — scope index

Working order for the holistic cleanup.

## Tier 1 — currently hot / highest risk
- TradingDesk
- AutoTrader V2
- AutoTrader V3
- Saxo execution/reconciliation
- account/product authority boundaries
- chart execution provenance
- live persistence and runtime diagnostics

## Tier 2 — next review
- Overview / main dashboard
- Strategy Lab
- market/price data services
- shared chart infrastructure
- shared navigation/layout
- background workers/stream services

## Tier 3 — broader module review
- Energy Radar / news/event ingestion
- remaining pages and experiments
- old POCs / compatibility modules
- unused/dead code
- docs/status duplication
- deployment/service ownership

## Deliverables
- living cleanup ledger
- dependency/boundary findings
- state/table ownership map
- canonical runtime flow maps
- dead/legacy module candidates
- observability plan
- incremental cleanup PRs protected by tests

Rule: do not let the broad audit destabilize the live trading core. Findings can be documented immediately; behavior changes are staged and verified.