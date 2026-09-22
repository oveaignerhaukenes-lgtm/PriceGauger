# AutoTrader v3 — Architecture Foundation

Status: accepted direction, 2026-09-22.

## Purpose

AutoTrader v3 is a clean rebuild around one autonomous trader per dedicated Saxo account. v2 remains operational while v3 is built beside it; no v2 execution path is silently migrated.

The architecture supports deterministic trading and progressively autonomous LLM-directed trading without allowing model creativity to corrupt broker reconciliation or cross account boundaries.

## Core pipeline

```
Market/Data
  -> Base Strategy
  -> Intelligence Supervisor
  -> Modifiers
  -> Risk / Capital Governor
  -> Target Inventory
  -> Execution / Reconciliation
  -> Saxo
  -> Observation / Audit
```

The universal strategy output is target inventory, not an order. Examples: `+0.07`, `0`, `-0.03`. Legacy LONG/FLAT/SHORT maps onto positive/zero/negative inventory. Only Execution/Reconciliation may submit broker orders.

## Isolation model

One AutoTrader owns one dedicated Saxo account. Account identity is the hard capital, P/L, margin and authority boundary. A trader must never infer or borrow authority from another trader/account. A separate Vault/Treasury account is outside every trader's execution authority.

## Control modes

- DETERMINISTIC: base strategy owns target before deterministic modifiers/risk.
- ADVISORY: AI records a counterfactual recommendation but cannot alter target.
- SUPERVISOR: AI may modify/cap/delay/flatten the base target inside an explicit risk envelope.
- AUTONOMOUS: AI may select existing strategies and parameters.
- GOD_MODE: experimental Danger Zone. AI may formulate hypotheses, create/version candidate strategies, run replay/shadow experiments, retire failed candidates and promote candidates according to configured permissions.

Even GOD_MODE cannot submit directly to Saxo, modify execution/reconciliation invariants, cross its account boundary, access Vault funds, or disable hard catastrophe/account limits. This is mechanical containment, not a requirement that trading decisions remain deterministic.

## Strategy Workshop and learning

AI-created strategies are versioned artifacts, not arbitrary source-code mutation. Each candidate has lineage:

`hypothesis -> expectation -> candidate -> replay/shadow -> actual result -> counterfactual -> lesson -> next hypothesis`

Preserve shadow worlds where practical so an AI override can be compared with the unmodified base strategy.

## MACD-Trailing

MACD-Trailing is the first native inventory strategy. It changes target inventory in 0.01-unit tranches as trend evidence accumulates or decays, up to the Capital Governor's permitted inventory. It may use the whole dedicated trader account as its capital allocation, but cannot bypass hard margin/catastrophe constraints.

## Modifiers and services

TakeProfit remains a composable modifier, not a strategy. Watchdog independently detects stale data/runtime, stuck transitions, target/position divergence and execution anomalies. Overseer evaluates trader behavior/performance over longer horizons and may feed Supervisor policy according to configured mode.

## TradingDesk contract

TradingDesk exposes only fast controls: AutoTrader ON/OFF; Family; Type; TakeProfit, Watchdog and Overseer toggles; a compact truth line showing strategy, base target, final target, actual Saxo inventory, pending delta and mode; and an action to open the full AutoTrader control room.

All tuning, AI permissions, strategy workshop, account configuration and detailed diagnostics belong in AutoTrader.

## AutoTrader control room

The landing view is a fleet view. Each trader shows dedicated account, equity/P&L history, strategy/version, control mode/AI status, the full target pipeline, margin utilization, modifier/service status, latest decision and health. Drill-down exposes configuration, decision provenance, execution ledger, experiments, strategy lineage and counterfactual performance.

## Vault / Treasury

Each trader has seed capital and a harvest high-water ledger. Default requested policy:

- harvesting activates after equity has increased 50% over seed/reference capital;
- after activation, 20% of subsequently realized harvestable profit goes to Vault;
- unrealized P/L is never harvested;
- already-harvested profit cannot be counted twice;
- transfers must preserve margin/catastrophe reserve;
- autonomous traders may request capital but never pull from Vault.

Exact Saxo account-transfer mechanics remain an adapter concern and must be verified before live use.

## Non-negotiable execution invariants

1. Every broker mutation has provenance: `broker order <- execution request <- approved target delta <- decision snapshot`.
2. Restart, UI refresh, model restart or strategy re-evaluation cannot themselves imply CLOSE.
3. Exact account + UIC + asset type identity is required.
4. Ambiguous broker states block conflicting mutation.
5. Reconciliation observes Saxo truth before claiming completion.
6. Strategy/AI produces intent; execution owns safe broker transition.
7. Every effective target transformation is auditable.

## Migration plan

Phase 0: stabilize v2 safety; unexplained CLOSE and live chart/data correctness remain blockers.

Phase 1: v3 read model beside v2 — Trader, AccountBoundary, DecisionSnapshot and TargetInventory contracts; observe v2 without order authority.

Phase 2: v3 execution adapter — reconcile one v3 target through the proven durable execution lifecycle.

Phase 3: MACD-Trailing — inventory-native, replay/shadow first, then bounded LIVE.

Phase 4: TakeProfit, Watchdog and Overseer against v3 contracts.

Phase 5: Vault ledger and verified account-transfer adapter.

Phase 6: Intelligence Supervisor — OFF/ADVISORY first, measured against deterministic counterfactual, then bounded SUPERVISOR authority.

Phase 7: AUTONOMOUS/GOD_MODE Strategy Workshop in an isolated experimental account.

## First implementation slice

Do not begin by rewriting the broker worker. Build pure v3 domain contracts and a read-only adapter from current v2/Saxo state. The first snapshot must state unambiguously:

`Trader -> account -> mode -> base strategy -> base target -> effective target -> risk-approved target -> actual inventory -> pending delta`

Only after this representation is stable should v3 gain order authority.
