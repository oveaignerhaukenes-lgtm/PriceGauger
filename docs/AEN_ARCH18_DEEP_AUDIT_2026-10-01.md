# Architect 18 — deep architecture audit notes

Date: 2026-10-01
Scope priority: TradingDesk + AutoTrader V2/V3 first; then prepare whole-project audit of Overview and remaining modules.

This is a working evidence notebook. Confirmed architectural actions are promoted into `AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md`.

## Audit questions

1. Where do V2 and V3 cross-import or share mutable runtime mechanisms?
2. Which modules create/own database schema and state?
3. Are there duplicate execution, reconciliation, sizing, authority, chart-marker or strategy activation paths?
4. Which Streamlit state is presentation-only and which accidentally influences runtime authority?
5. Can every trade be traced decision -> target -> request -> broker -> observed position -> reconciliation?
6. Which compatibility/legacy layers are still runtime dependencies?
7. Which expensive read/replay paths share process/refresh boundaries with live trading?
8. What should be stabilized before auditing Overview and older modules?

## Confirmed evidence so far

### Cross-engine dependency
`autotrader_macd_a_pyr_live_v1.py` imports V3 order guard and V3 position reconciliation while also using V2 strategy enrollment. This is a concrete engine-boundary violation and should be decomposed, not merely renamed.

### V3 schema ownership is distributed
Schema creation is currently embedded across multiple runtime/config modules, including config, order guard, live runtime, SIM authority, LIVE authority, execution store, execution policy, modifier settings and closed-bar driver. This increases the effort required to understand persistent state and migrations.

Audit direction: determine whether schema bootstrap/migrations can become centralized while domain repositories retain read/write ownership.

### Runtime-created schema
At least `autotrader_v3_live_runtime_v1.py` creates its runtime-state table inside runtime recording code. This is operationally convenient but makes schema lifecycle implicit. Flag for DB audit; do not change until restart/deploy semantics are understood.

## Next passes

- Search V2 -> V3 and V3 -> V2 imports systematically.
- Inventory execution/reconcile modules and their callers.
- Inventory `CREATE TABLE` ownership.
- Search direct session-state authority mutations.
- Map TradingDesk render tree and refresh domains.
- Map current Overview/pages after trading core is understood.
