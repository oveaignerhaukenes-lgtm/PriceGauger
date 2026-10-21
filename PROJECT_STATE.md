# PriceGauger — project continuity (living state)

**Entry point for every new ChatGPT/developer session.** Read this file, then inspect fresh `main`, relevant code/tests, open PRs, CI and Railway runtime before asserting current status.

## Source of truth

1. GitHub `main` code/tests + git/PR history: implemented behavior.
2. Railway deployed commit and service logs: deployed behavior (not proof of broker fills).
3. PostgreSQL/Saxo reconciliation: actual account/position/P&L evidence.
4. This file: compact human-readable decisions, priorities and outstanding questions. It can lag code and runtime; verify.

Never treat an earlier handoff, chat response, or this file alone as proof of LIVE readiness.

## Architecture in one minute

PriceGauger: canonical market data → Technical Core → optional analytical layers → TradingDesk / AutoTrader. PostgreSQL is production shared state. Railway services: `pricegauger-web`, `PriceGauger-worker`, `PriceGauger-stream`, PostgreSQL.

AutoTrader V3: canonical instance registry → per-instance config → catalog strategy → runtime strategy → exact account/product ownership and LIVE authority → durable broker order → reconciliation.

The separate V2/Lager account must not accidentally acquire V3 authority. Preserve all LIVE execution safeguards and exact account/product isolation. Reference: `docs/PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md` (historical checkpoint, not current production claims).

## Working priorities (user intent; verify current implementation)

- Make approved V3 strategies available through the normal LIVE controls only after runtime mapping and safety checks.
- Capture **account equity/balance and realized results over time**, and align intervals with the active strategy, instrument and instance. Unfunded accounts should not be mistaken for losses.
- Compare live strategy outcomes across market regimes; retain a compact auditable history.
- Improve responsiveness without duplicating canonical data loading.
- Keep SIM and LIVE evidence clearly separate.

## Current verification status

- **Code head:** resolve from GitHub on every session (do not pin a mutable SHA here).
- **Open PRs/CI:** inspect live; journal below is supplemental.
- **Railway deployed SHA (verified 2026-10-21 ~01:15 UTC):** `4a9c571737d0a9619be254c4b17a9251070bbb27` was reported `SUCCESS` on all five app services (web, worker, stream, Spring engine, Live-Sim). Runtime logs show V3 managing existing instances, not evidence of a HyperChase fill.
- **Saxo positions, arming, margin, trades and balances:** NOT broker-reconciled by this handoff. A portfolio screenshot shown 2026-10-21 displays several profitable Tech100 accounts, but is not proof of HyperChase fills or net strategy attribution; do not commit private balance figures.
- **Latest tested capabilities:** derive from current code/tests and PRs, not old handoffs.

## Active work ledger (maintained by the acting developer)

Update this small section in the same PR whenever a change affects architecture, strategy semantics, data contracts, execution, or user-visible behavior.

| Topic | State | Next evidence/action |
| --- | --- | --- |
| HyperVigilant Chase 10s LIVE | **Merged [#775](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/775)** (`4a9c5717`), CI green, five Railway app services SUCCESS; real LIVE catalog FAST/FILTERED, no automatic arming | Check continuous genuine 1s BBO on exact Tech100 UIC + decision/close/reconcile/open timestamps; use separately bounded account only after explicit user selection |
| HyperVigilant direct reversals | V3 target changes LONG↔SHORT immediately on 10s impulse; execution is guarded CLOSE → Saxo FLAT reconciliation → fresh-signal OPEN | No atomic opposite-side netting and no guaranteed 10s Saxo fill; report actual latency/failures |
| HyperVigilant PAPER | Merged [#774](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/774) (FAST/FILTERED) on prospective Saxo BBO in Strategilab v2 | Compare realized PAPER signal-to-next-quote delay, actual quote density, and net after spread/slippage in matched regimes; do not infer Saxo fills |
| Project continuity | Active: `PROJECT_STATE.md` authoritative decision/sync summary + automated git journal | Verify journal workflow runs after each merge |
| V3 LIVE strategies | Verify fresh main | Map catalog/runtime/arming; check recent PRs and CI |
| Account-level outcome collection | User priority, implementation unverified | Inspect Saxo account snapshots, DB schema and strategy assignment history |
| UI performance | Investigation requested | Profile first; avoid redundant polling and queries |

## Important decisions / invariants

- GitHub + Railway + database are authoritative, not chat memory.
- One bounded change per PR, test, guarded merge, verify Railway SHA and runtime.
- Never infer live order fills, equity, or profit from a simulation or UI arrow.
- Account results must be associated with strategy **effective-time intervals**; handle deposits, withdrawals, FX and financing/fees distinctly to avoid false attribution.
- Update human decisions deliberately: automation can record commits but cannot infer the intent or success of a strategy.
- **HyperChase 10s** requires actual, fresh Saxo bid/ask samples from exact UIC;
  unlike 1m strategies it wakes on fresh quote progress. If 1s feed is sparse,
  stale or the Saxo cost/precheck/order chain is slow, it MUST hold/fail closed.
  Changing a target sign does not mean broker crossed sides in one order;
  V3 still closes, reconciles, then opens if a new signal is valid.
  Deployment must never arm or switch any account automatically.
- Secrets, Saxo identifiers, detailed personal/account balances and sensitive runtime logs should not be committed to this public repository.

## Automated journal

`docs/PROJECT_CHANGELOG.md` is a bounded machine-maintained record of merged `main` revisions; `.github/workflows/project-continuity.yml` refreshes it. It records repository changes, **not** deployment success or trading outcomes.

## Session closing protocol — replaces handoffs

At the end of meaningful work, update this file within the relevant PR with:
- what actually changed (code paths/PR);
- what was tested and the result;
- what was deployed and verified, or explicitly *not verified*;
- remaining concrete blocker and next step.

Keep it concise: prune completed items, retain durable decisions, link PRs for details. A new chat starts here; there is no need for a narrative handoff.

### Last verified handoff (2026-10-21 UTC)

- **Delivered:** quote-driven HyperChase FAST/FILTERED LIVE in normal V3 chooser (#775), continuous prospectively sampled 1s PAPER experiment (#774), guarded close→broker-flat→fresh-quote open; no account enabled by deployment.
- **Validated:** GitHub CI for #775 green; Railway all five app services deployed merge SHA `4a9c5717` SUCCESS. This verifies delivery, not ≤10s broker execution.
- **Next action:** measure per-UIC `lsim_hyper_quotes_1s` sample gaps, quote age and true BBO freshness; run limited prospective PAPER comparison, then, only with explicitly selected small LIVE account, check ORDER/PENDING/RECONCILED timestamps, margin and fees. Any missing data means do not open automatically.
- **Synchronization:** update this same file in the PR for each substantive feature; auto-generated changelog is supplementary. No additional narrative handoff needed.

