# V3 protective LIVE buttons — impulse exit, account loss lock and per-button audit (2026-10-27)

## Explicit user intent
Expose newly built risk guards in each V3 LIVE instance as *opt-in*, but do not
auto-select them for currently trading accounts. Show every modifier button
in last-saved-change order (newest first), and place one per-modifier Logg
channel next to the button. Maintain existing V3 Saxo ordering, pending locks,
position verification, account boundary and margin checks.

## LIVE scope / semantics
- Impulse Exit: genuine timestamped 1s Saxo bid/ask from existing
  lsim_hyper_quotes_1s, exact instrument UIC. Compare last observed 10-second
  movement against 9bp minimum and 3× robust historical 10s move.
  **Opposing** extreme move for held inventory yields target FLAT; after
  actual broker CLOSE, remain flat through 25s of quiet signal before base
  strategy can reenter. Missing/late/gapped quote quality blocks new exposure
  but is not grounds to send an unverified emergency CLOSE. Persist latch
  per instance, instrument, account and currency.
- Account Loss Lock: uses fresh Saxo exact AccountKey+ClientKey /balances,
  verifies returned currency and CalculationReliability == Ok, observes
  TotalValue high-water mark in same risk context. -5/-8% veto new OPEN/ADD;
  -10% latch proposes FLAT and continues blocking new exposure even if balance
  later recovers. Human-only reset requires verified *exact* Saxo FLAT and
  positive verified Saxo TotalValue.
- The existing V3 worker evaluates these alongside the configured strategy,
  resolves target, executes via established pending/reservation/precheck and
  broker-confirmed reconciliation. No independent order issuer, no disabled
  existing safety checks and no automatic rearming.
- The desired 10–15% worst-case account loss is NOT guaranteed by these rules.
  Worker scans accounts serially, quote sampling can be stale/unavailable, Saxo
  might reject or delay a CLOSE, market gaps/spread/slippage exceed thresholds,
  and raw Saxo NAV can shift due to manual cashflows. Guard is separate from
  server-side protective stop orders.

## Important limitations to validate before enabling
1. Confirm actual 1s UIC=4912 quote density and worker loop cadence in Railway.
   This new impulse guard evaluates at **worker cycles**, not a guaranteed
   one- or five-second interrupt; do not label it a hard real-time stop.
2. Saxo TotalValue across deposits, withdrawals and account adjustments is
   not flow-adjusted strategy profit. If user deposits/withdraws while guard is
   enabled, operator must review anchor; automated inference is invalid.
3. Strict account reliability/currency/market data checks; unavailable evidence
   blocks new risk, and open risk still relies on existing base exit until
   reliable adverse impulse or drawdown evidence is available.
4. A 10% cap should ultimately use margin/equity-aware account and position
   guard corroborated against Saxo fills, realized costs and money movements,
   preferably paired with exchange/broker-native stops.
5. Per-button log shows target changes and status transitions, **not proof of
   Saxo fills**; inspect canonical V3 broker reconciliation for actual execution.
6. Other legacy 'Impulse Detector' (old non-live placeholder) and
   'Volatility Pause' (only OPEN/ADD veto) are not silently redefined.
   New Impulse Exit and Account Loss Lock are separately named LIVE modifiers.

## Deployment
Opt-in availability is implemented via V3 registry LIVE modifier allowlist,
V3 control panel and V3 runtime pipeline. Both new modifiers are OFF by default
and require the user to save the selection for each instance.
All buttons are sorted by durable latest saved selection change in the control
UI. Generic legacy modifiers also log modifier target transitions, vetoes and
when no evidence was available. An audit event records the intended target but
must not claim a confirmed Saxo fill.

## Test gates
CI: exact-BBO causality/quality, adverse-vs-favorable direction, quiet recovery,
drawdown latch/reset, no blind order, immutable audit, chronology, compile and
existing full-regression tests. Railway must show same feature deploy on both
web and worker; user activation is separate and requires monitoring.
