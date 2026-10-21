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

- **Deployment blocker (2026-10-21 ~08:xx UTC):** Railway `connect_service_source` to rebuild existing worker from GitHub `main` returned `Deploys have been paused temporarily`. GitHub #780/#782 merged with green CI but their code has **not** been shown deployed by Railway. Keep prior runtime SHA distinct from Git HEAD; account LIVE remains off. Do not claim a new deploy or automatic rearm.

- **Code head:** resolve from GitHub on every session (do not pin a mutable SHA here).
- **Open PRs/CI (inspected 2026-10-21):** #721 (Unngå tap V1) is the only open PR and remains DRAFT; do not merge without separate review. Recheck every session; this journal-maintenance PR is not included in that snapshot.
- **Railway deployed SHA (verified 2026-10-21 ~01:37 UTC):** all five app services (web, worker, stream, Spring, Live-Sim) are `SUCCESS` at journal-only commit `a7501fd9f823f86a18199864203cf85cba7ccd93`. This verifies deployment health, not trade fills or strategy P/L. The last HyperChase functional change remains #775.
- **Saxo positions, arming, margin, trades and balances:** NOT broker-reconciled by this handoff. A portfolio screenshot shown 2026-10-21 displays several profitable Tech100 accounts, but is not proof of HyperChase fills or net strategy attribution; do not commit private balance figures.
- **Latest tested capabilities:** derive from current code/tests and PRs, not old handoffs.

## Active work ledger (maintained by the acting developer)

Update this small section in the same PR whenever a change affects architecture, strategy semantics, data contracts, execution, or user-visible behavior.

| Topic | State | Next evidence/action |
| --- | --- | --- |
| HyperVigilant Chase 10s LIVE | **Merged [#775](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/775)** (`4a9c5717`), CI green, five Railway app services SUCCESS; real LIVE catalog FAST/FILTERED, no automatic arming | Check continuous genuine 1s BBO on exact Tech100 UIC + decision/close/reconcile/open timestamps; use separately bounded account only after explicit user selection |
| HyperVigilant direct reversals | V3 target changes LONG↔SHORT immediately on 10s impulse; execution is guarded CLOSE → Saxo FLAT reconciliation → fresh-signal OPEN | No atomic opposite-side netting and no guaranteed 10s Saxo fill; report actual latency/failures |
| Tech100 2m late-reversal audit (2026-10-21 12:28 Oslo) | Saxo 1m screenshot showed rebound from ~12:15, first blue buy marker near 12:28. Railway V3 worker f3e65462 (historically Hvelvet; verify current mapping) maintained `actual=-0.01,target=-0.01` from 10:10–10:27 UTC, first `target=+0.01` at 10:28:05, submitted CLOSE Buy 0.01 at 10:28:06, confirmed FLAT 10:28:17, submitted OPEN Buy 0.01 at 10:28:36, confirmed `+0.01` 10:28:45. Another instance b6008676 OPEN Buy 0.01 at 10:29:07. This is **late decision**, not predominantly Saxo transmission lag. HyperChase b800fdec remained target/actual zero during observed window (LIVE arming should not be inferred from this alone). | Determine current V3 strategy key for f3 from live config before changing model. Test price-first early exit/early reversal versus current 2m behavior prospectively with spreads/whipsaw costs. This PR adds only per-minute deduplicated `SIGNAL_TRACE` (actionable raw target, approved target, decision key and reason; no extra Saxo/AI). Do not auto-change active strategies. |
| HyperChase LIVE audit (2026-10-21) | Read-only worker logs: one HyperChase LIVE instance was cycling but `volatility-pause data_ok=False` because safety 1m bars were not loaded; operator disabled LIVE and the last exact observed Saxo position/target were both `0`. **Fix #780 merged and CI green**: 1m safety bars are loaded separately, cached per minute; 10s BBO entry/exit signals and Saxo reconciliation path unchanged. | **NOT DEPLOYED/NOT LIVE**: Railway API rejected worker source reconnect on 2026-10-21 with `Deploys have been paused temporarily`. Wait for Railway deploys to resume, verify deployed SHA and runtime safety evidence, then recheck account ownership, order state and explicit arming before LIVE. |
| HyperChase 1s input diagnostics | **#782 merged, CI green, NOT DEPLOYED:** bounded read-only BBO quote-quality probe measures genuine 60s samples, spread, max gaps, age and qualifying 10s windows independently of LIVE arming. | After Railway resumes, deploy worker from fresh main, inspect `hyper chase BBO QUALITY` once-minute logs for the exact Tech100 UIC. No automatic arming on deployment; do not claim 10s fills until actual Saxo timestamps are reconciled. |
| HyperVigilant PAPER | Merged [#774](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/774) (FAST/FILTERED) on prospective Saxo BBO in Strategilab v2 | Compare PAPER signal-to-next-quote delay, quote density and net after costs; do not infer Saxo fills |
| Strategilab v2 | Isolated historical multi-replay, Saxo cost/account overlays (#771); 18 V3 replay routes and chart scrubbing (#772); bounded AI error handling (#773); quote-based HyperChase PAPER (#774) | Check model/replay coverage and costs against real account/product data; maintain historical replay vs prospective PAPER vs LIVE evidence separation |
| Project continuity | #777 merged with green CI; GitHub Actions successfully updated `docs/PROJECT_CHANGELOG.md` on `main` at bot commit `a7501fd9` (2026-10-21). In Railway production all five app services have watch patterns: include `**`, exclude `/PROJECT_STATE.md` and `/docs/PROJECT_CHANGELOG.md`. | Verified: #778 docs-only merge `c7e22742` and resulting journal bot commit `53462b54` were `SKIPPED` by Railway on all five services; the Git journal still advanced. Recheck future runtime code deploys normally; bot journal never asserts LIVE readiness |
| V3 LIVE strategies | LIVE route additions merged for rhythm (#753/#755), MACD setups (#765/#766) and HyperChase (#775). Catalog presence is not per-account arming or broker success | Verify exact catalog-to-runtime mapping, live safeguards, instance assignment and broker evidence before changing any account |
| Account-level outcomes | NAV + strategy epochs and Saxo/EOD/TWR collection paths merged (#749–#752, #757–#758); Strategilab v2 account performance UI merged (#771). Code presence does not establish complete broker-reconciled history or causal attribution | Validate real Saxo snapshots and freshness, cash-flow/FX/fee handling, effective-time strategy joins and P&L consistency before ranking LIVE strategies |
| Railway CPU/DB cost audit 2026-10-21 | Railway production 6h mean vCPU: stream 1.108, Postgres 1.093, worker 0.550; mean Postgres memory 2.52 GB. Stream logs show historical V2 MACD dry-run, Fast15, MTF and Cocktail loops every 30–60s across 8 markets; some fetch up to 50k–100k historical points per market. Also 60s freshness probe read 2h of three-source history per market. PAPER Lab AI technical/context pair loops start automatically, with independent max call budgets 80/480 daily, **not actual measured calls**. | In this PR legacy V2 research loops default OFF (`PRICEGAUGER_LEGACY_SHADOW_RESEARCH=1` to restore), PAPER technical/context LLM loops independently opt in (`PRICEGAUGER_LAB_AI_TECH_ENABLED=1` / `PRICEGAUGER_LAB_AI_PAIRS_ENABLED=1`); freshness probe reduces read window 2h→15m, limit 5000→20. Keeps Saxo feed, V2/V3 LIVE risk/open/close/positions, official account snapshots, 1s Hyper PAPER, normal Lab and V3 AI manager unchanged. **Not deployed/measured**. Check CI, Railway builds and compare matched 6h CPU/DB metrics. |
| Stream registry/Saxo auxiliary scans | Identified `realtime_worker._watch_v2_registry` polls every 15s and calls `load_runtime_instruments_v2`, which previously always performs Saxo open-position discovery, futures rollover audit and discovered instrument history readiness checks on each poll. | Separate fast local 15s subscription lookup from auxiliary Saxo discovery/rollover/history refresh (default 300s, bounded min 60s, once immediately on worker startup). PR under review; test and verify market subscription updates remain responsive. Open position/account truth collection and LIVE risk/close remains independent. |
| UI performance | Incremental UI/chart reads and reduced duplicate DB work merged (#736/#737/#739); no measured production latency profile in this file | Measure p95 UI latency and per-session query/refresh load before further restructuring |

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

`docs/PROJECT_CHANGELOG.md` is a bounded, deterministic record of non-bot `main` commits; `.github/workflows/project-continuity.yml` refreshes it after merges and daily. Verified after #777: bot commit `a7501fd9` advanced the journal on `main`. Railway production watch patterns explicitly exclude this file and `PROJECT_STATE.md` from triggering docs-only redeploys (configuration read back from all five app services, 2026-10-21). Post-merge proof: Railway marked #778 (`c7e22742`) and its generated journal commit (`53462b54`) `SKIPPED` on all five app services while recording the updated journal on `main`. The filter does not alter trading runtime and is intended to leave code-change deployments enabled. Journal entries are **not** evidence of deployment success or trading outcomes.

## Session closing protocol — replaces handoffs

At the end of meaningful work, update this file within the relevant PR with:
- what actually changed (code paths/PR);
- what was tested and the result;
- what was deployed and verified, or explicitly *not verified*;
- remaining concrete blocker and next step.

Keep it concise: prune completed items, retain durable decisions, link PRs for details. A new chat starts here; there is no need for a narrative handoff.

### Most recent operational checkpoint (2026-10-21 UTC)

- **Delivered:** quote-driven HyperChase FAST/FILTERED LIVE in normal V3 chooser (#775), continuous prospectively sampled 1s PAPER experiment (#774), guarded close→broker-flat→fresh-quote open; no account enabled by deployment.
- **Validated:** GitHub CI for #775 green; Railway all five app services deployed merge SHA `4a9c5717` SUCCESS. This verifies delivery, not ≤10s broker execution.
- **Next action:** measure per-UIC `lsim_hyper_quotes_1s` sample gaps, quote age and true BBO freshness; run limited prospective PAPER comparison, then, only with explicitly selected small LIVE account, check ORDER/PENDING/RECONCILED timestamps, margin and fees. Any missing data means do not open automatically.
- **Synchronization:** update this file in each substantive PR; the Git journal is now verified to update automatically after a merge, but documents only commit provenance. Recheck bot writes and Railway watch-path behavior if either is reconfigured.

