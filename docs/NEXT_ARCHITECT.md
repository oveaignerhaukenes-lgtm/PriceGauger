# PriceGauger — Next Architect

Updated: 2026-09-04

The authoritative handoff for Arkitekt 9 is now:

**[`docs/ARCHITECT_HANDOFF_2026-09-04_ARKITEKT9.md`](ARCHITECT_HANDOFF_2026-09-04_ARKITEKT9.md)**

Read that document in full before changing AutoManager, strategy runtime, Saxo execution, Strategy Series/Snapshot Spine, or futures identity/lifecycle behavior.

## Starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Runtime `main` immediately before the documentation handoff branch:

`f28d70dc1ae9d5e284e2cf4334a2f34adb1829c8`

That runtime baseline contains PR #297 (**hybrid re-entry fix + pure 5m MACD LIVE**) on top of PR #298 (**linked chart cursor/refined gestures**). The handoff documentation merge will move `main` again without changing runtime behavior.

Always refresh from current `main` before branching.

## Immediate orientation

The control plane is now **AutoManager Simple Core**: durable BUY/SELL user targets, a product-level Manage position toggle, and one hot-switch strategy dropdown. Strategy code emits targets/requests only; Saxo order authority remains in the hardened execution lifecycle.

The strategy laboratory is persisted through **Snapshot Spine + Strategy Series**. TradingDesk P/L/model views read stored series rather than replaying historical strategy logic on render. Pure MACD controls are deliberately maintained as benchmarks against hybrids, Strong Cocktail and the AI baseline.

Important recent strategy state:

- pure 1m, 2m, 5m and 15m MACD flip are LIVE-selectable controls;
- 10m and 20m remain shadow controls;
- pure 5m uses the exact same persisted strategy identity in simulation and LIVE;
- 1m-exit/2m-entry and 1m-exit/5m-entry hybrids are LIVE-selectable;
- PR #297 fixed hybrid FLAT re-entry so a 1m recovery can re-enter when the slower closed MACD regime is already aligned, without requiring a second slow cross;
- Strong Cocktail is LIVE-selectable and retains the asymmetric fast-exit/stronger-re-entry philosophy;
- GPT-5 mini AI baseline is LIVE-selectable but has no sizing/order authority.

## Critical lifecycle update

Do not restore the old rule that realized P/L settlement must finish before opposite re-entry.

Current lifecycle after PR #294 is:

`target -> CLOSE -> PG close accepted/reconciled -> exact Saxo FLAT -> OPEN opposite`

Realized P/L settlement may catch up as a separate accounting/audit path. `SUBMITTING` / uncertain close remains blocking.

## Immediate next work

1. Refresh production truth: active strategy, exact Saxo position, execution requests and Railway logs.
2. Observe the next natural close/re-entry or reversal end-to-end; recent user testing specifically exposed strategies that closed but failed to open again.
3. Compare **pure 5m MACD** against the corrected **1m-exit / 5m-entry hybrid** as an explicit control experiment.
4. Verify corrected hybrid re-entry in a natural episode where the slower regime remains aligned through a fast 1m exit/recovery.
5. Continue Strong Cocktail vs simple controls across independent regimes before assuming the complex model wins.
6. Diagnose `sp500 CFD: invalid 5m ATR` as a source/canonical-bar data-quality problem; do not weaken the ATR validity gate.
7. Continue gradual native incremental Strategy Series production where useful; never return replay-on-render to TradingDesk.
8. Keep futures ContractLifecycle/Rollover as an explicit future capability before autonomous expiring-futures management.

Full current invariants, recent PR rationale, Railway identities, strategy matrix, UI architecture, known issues and recommended working sequence are in the Arkitekt 9 handoff.
