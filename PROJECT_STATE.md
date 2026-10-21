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
- **Railway deployed SHA, health and logs:** not verified by creating this document.
- **Saxo positions, arming, margin, trades and balances:** not verified by creating this document.
- **Latest tested capabilities:** derive from current code/tests and PRs, not old handoffs.

## Active work ledger (maintained by the acting developer)

Update this small section in the same PR whenever a change affects architecture, strategy semantics, data contracts, execution, or user-visible behavior.

| Topic | State | Next evidence/action |
| --- | --- | --- |
| HyperVigilant Chase 10s LIVE | PR in progress: quote-based FAST/FILTERED in canonical V3 LIVE, no automatic arming | Verify CI and Railway SHA; manually select a separately bounded Tech100 account; check genuine 1s BBO coverage and broker order latency |
| HyperVigilant direct reversals | V3 target changes LONG↔SHORT immediately on 10s impulse; execution is guarded CLOSE → Saxo FLAT reconciliation → fresh-signal OPEN | No atomic opposite-side netting and no guaranteed 10s Saxo fill; report actual latency/failures |
| HyperVigilant PAPER | Existing prospective quote 1s PAPER experiments `CHASE_10S_FAST`/`CHASE_10S_FILTERED` in Strategilab v2 | Compare net after spread/slippage with matching market regimes before expanding risk |
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
