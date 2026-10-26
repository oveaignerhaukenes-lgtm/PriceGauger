# PriceGauger — project continuity (living state)

**Entry point for every new ChatGPT/developer session.** Read this file, then inspect fresh `main`, relevant code/tests, open PRs, CI and Railway runtime before asserting current status.

## Source of truth

1. GitHub `main` code/tests + git/PR history: implemented behavior.
2. Railway deployed commit and service logs: deployed behavior (not proof of broker fills).
3. PostgreSQL/Saxo reconciliation: actual account/position/P&L evidence.
4. This file: compact human-readable decisions, priorities and outstanding questions. It can lag code and runtime; verify.

Never treat an earlier handoff, chat response, or this file alone as proof of LIVE readiness.

## Latest verified handoff — 2026-10-23 18:26 UTC

- **GitHub journal current through [#799](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/799)**: `docs/PROJECT_CHANGELOG.md` includes main merge `21f8566b1952` (2026-10-23). It is an automatic record of commits, not an account or fill report.
- **V3 trade-marker request delivered — #799 merged** (`21f8566b1952`): V3 reconciled executions are displayed as small BUY-up / SELL-down triangles, anchored to actual candle time/price, without verbose label/square for FLAT. Shared Lightweight charts and V3 instance inspection were updated. Presentation-only; historical/manual fills and separate AI annotations retain their contracts. Do not confuse triangles with entry *signals*: they depict recorded executions.
- **Duplicate 1m/2m MACD+Stochastic crash repaired — [#798](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/798)** (`829d27493128`): duplicate-bar `HOLD_DUPLICATE` decision envelope fixed, idempotency tested, no strategy parameter/arming change.
- **Railway verification at 18:26 UTC:** all five app services (web, worker, stream, Spring Trade Engine and Live-Sim) reported `SUCCESS` for deployment SHA `262d03dcff839e`, newer than #798/#799. This is runtime *deployment* evidence only; it does not establish specific Saxo fills, P/L, 10s reversal latency or which strategy a given account is running.
- **Next review:** visually verify triangles on chosen LIVE chart against exact account-scoped reconciled Saxo execution events; check label clarity on mobile. Continue HyperChase quote-quality/gate audit and Strategilab v2 replay validation separately; never auto-switch or arm accounts because docs were updated.
- **Continuity status:** human-readable `PROJECT_STATE.md` updated alongside the already-current automatic Git journal. The docs-only update should not redeploy trading code; if CI/journal advances, confirm GitHub history but do not infer LIVE changes.

## Saxo OAuth incident — 2026-10-23 (Arkitekt 18)

- Railway `PriceGauger-stream` runtime reports repeated Saxo `/token` HTTP **401 with non-JSON body** (observed 18:31 UTC and later); the current implementation surfaces this as misleading `INVALID_RESPONSE`. `PriceGauger-worker` later reports `REAUTH_REQUIRED: Saxo er ikke koblet til`, after the shared token was removed. Both are runtime observations, **not a verified Saxo root cause**.
- All required Saxo environment **variable names** exist on `pricegauger-web`; OAuth connector redacts their **values**. Redirect URI, AppSecret, LIVE/SIM consistency and actual registered app callback cannot be verified from Railway tooling alone. Saxo documentation confirms LIVE auth host `live.logonvalidation.net`, HTTP Basic exchange, and rotating refresh tokens. Existing PostgreSQL advisory transaction lock appears correctly scoped for cross-service refresh serialization; no proof of race.
- Isolated diagnosis PR on `fix/saxo-oauth-401-diagnostics-20261023`: classify non-JSON 401/403 as `REAUTH_REQUIRED`, 429 as `RATE_LIMITED`, 5xx as `AUTH_SERVICE_ERROR`; emit only allowlisted content-type and X-Correlation metadata, never HTTP body/token/key/state. Log callback outcome category without identifiers. Correct hardcoded SIM text when LIVE is selected. Tests added; **NOT MERGED / NOT DEPLOYED** at authoring time.
- **Upstream check 2026-10-23:** Saxo help article last updated **2026-10-20** documents a new per-login-session SMS challenge before first trade (and ~45s initial delay). It does **not** establish that OpenAPI OAuth changed. Saxo's current documentation still recommends server-side OAuth Authorization Code Grant with HTTP Basic `client_id:client_secret`, matching our implementation. The official planned-changes page contains no announced retirement of this OAuth grant. Saxo OpenAPI support notes sessions can exceptionally be terminated after new regulatory/disclaimer confirmation; correlation with current HTTP 401 is plausible but unproven. Compare LIVE app registration status, secret pair, redirect URI and environment securely, then observe one fresh browser OAuth callback. Sources: https://www.help.saxo/hc/en-us/articles/39991803413789-Why-am-I-seeing-a-Verification-required-message-when-trading ; https://developer.saxobank.com/openapi/learn/oauth-authorization-code-grant ; https://openapi.help.saxo/hc/en-us/articles/4416637197457-Can-Certificate-Based-Authentication-CBA-be-enabled-for-my-app .
- Next: full CI, review, merge/deploy only with normal release safeguards; manually initiate new Saxo login in a fresh browser, verify callback and resulting token in the shared PostgreSQL store (without exposing values), then confirm worker + stream recover. If 401 continues, Saxo OpenAPI support requests timestamp, HTTP status and `X-Correlation`; investigate app secret, redirect and upstream Saxo gateway/security filters. **Do not auto-arm, place test orders, or assume account positions from stale UI**.

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

## HyperChase and LIVE worker check (2026-10-23 07:55 UTC)

- Five Railway app deployments: `SUCCESS` commit `2aa2f639fc18` (2026-10-22); verify new deploy SHA after the fix PR.
- Saxo Tech100 UIC 4912 genuine BBO quality improved: last 60s typically 47–53 received quotes, latest ~1–3s old, valid 10s windows present. This is an input-quality check, NOT evidence of profitability or ten-second fills.
- No `hyper-chase-10s-*` LIVE SIGNAL_TRACE / GATE_SUMMARY in the inspected 2026-10-22/23 logs. Five armed LIVE instances running other strategies; in particular `b800fdec` (historically Tech100-E) showed `rhythm-trend-1-v1` signals, not HyperChase, and broker-target/actual +0.01 at 07:54 UTC. **Do not assume HyperC is active, and do not change any user's arming/strategy choice.**
- Critical unrelated worker fault: repeated `TypeError: MacdStochDecisionV3.__init__() missing stochastic_k/stochastic_d` on duplicate 1m/2m bar. `autotrader_v3_closed_bar_driver_v1.py` built a four-argument `HOLD_DUPLICATE` with six-field Stoch V1 type. A small no-op decision-envelope fix is under isolated PR, with idempotency tests, no strategy or Saxo-order change. Verify GitHub CI and matching Railway worker deployment before declaring repaired.
- HyperChase opposite target is immediate, but actual Saxo reversals remain protected CLOSE → broker-confirmed FLAT → fresh signal OPEN; not an atomic net flip.

## Current verification status

- **Railway production build pause reconfirmed 2026-10-21:** an attempted source reconnect of isolated LiveSimLab from GitHub `main` returned `Deploys have been paused temporarily`. Cost saving PRs #784, #786 and #788 are merged with green CI, but no matching new production deployments observed. Do not claim reduced billed consumption yet. Preserve LIVE and account controls. Once Railway resumes, roll out LiveSimLab, stream and worker deliberately, check their deployed SHAs, then compare comparable 6h CPU/RAM and DB growth; stop if runtime regressions.

- **Deployment blocker (2026-10-21 ~08:xx UTC):** Railway `connect_service_source` to rebuild existing worker from GitHub `main` returned `Deploys have been paused temporarily`. GitHub #780/#782 merged with green CI but their code has **not** been shown deployed by Railway. Keep prior runtime SHA distinct from Git HEAD; account LIVE remains off. Do not claim a new deploy or automatic rearm.

- **Hunter/Rabid 2026-10-21 latest:** #792 merged, complete CI passed; Railway worker rebuild denied `Deploys have been paused temporarily`. Production does NOT expose new engines yet; app/worker are unchanged. No account activation or orders by this work.
- **Code head:** resolve from GitHub on every session (do not pin a mutable SHA here).
- **Open PRs/CI (inspected 2026-10-21):** #721 (Unngå tap V1) is the only open PR and remains DRAFT; do not merge without separate review. Recheck every session; this journal-maintenance PR is not included in that snapshot.
- **Railway deployed SHA (verified 2026-10-21 ~01:37 UTC):** all five app services (web, worker, stream, Spring, Live-Sim) are `SUCCESS` at journal-only commit `a7501fd9f823f86a18199864203cf85cba7ccd93`. This verifies deployment health, not trade fills or strategy P/L. The last HyperChase functional change remains #775.
- **Saxo positions, arming, margin, trades and balances:** NOT broker-reconciled by this handoff. A portfolio screenshot shown 2026-10-21 displays several profitable Tech100 accounts, but is not proof of HyperChase fills or net strategy attribution; do not commit private balance figures.
- **Latest tested capabilities:** derive from current code/tests and PRs, not old handoffs.

## Active work ledger (maintained by the acting developer)

Update this small section in the same PR whenever a change affects architecture, strategy semantics, data contracts, execution, or user-visible behavior.

| Topic | State | Next evidence/action |
| --- | --- | --- |
| Probability Lab 1m (2026-10-26) | Isolated read-only Markov(1–3), historical-rate baseline and Poisson/Skellam minute-sign proxy with 1/2/5/10m walk-forward on exact canonical 1m instrument bars; no Saxo trading/tick storage. Implementation proposed on `feature/probability-lab-1m-20261026` (PR pending). Distinct from draft Probability Desk #804 (daily/macro research). | Run CI and real subscribed Tech100 walk-forward, inspect Brier/calibration/sample counts. Verify deployed web SHA after merge; no LIVE implications. Future: separately design bounded persisted BBO sampling if tick-Hawkes is desired. |
| PriceTrend #1 (2026-10-22) | Research-only Tech100 price-first strategy + SMA9/21 benchmark wired to Strategilab v2 historical replay and V3 SIM registry. Completed 5m SMA9/21 + 21-slope / ATR14 + 12-bar price efficiency owns direction; completed 2m SMA9 times one legal tranche; price + 2.5 ATR rolling invalidation permits existing SHORT through MACD/Stoch counter-pulses; missing/gapped 1m source goes FLAT. No VWAP volume reliance, no extra Saxo/AI ingestion. | Run green CI and **matched Tech100 actual historical 1m** replay vs SMA9/21 baseline, incl Oct 22 overnight and sideways periods, with costs/first entry lag. Explicit LIVE denial in config and adapter; user must separately request/approve LIVE after cost/risk evidence. See `docs/PRICETREND_REGIME_1_TECH100_20261022.md`. |
| TradingDesk falsely labels Tech100-E `free` (2026-10-21 ~19:22 Oslo) | The V3-tab `tradingdesk_automanager_simple_v1.py` only consults historical `pg_v2_autotrader_strategy_enrollments` for selected account, omitting enabled `autotrader_v3_engine_instances` and exact `autotrader_engine_account_ownership`. Screenshot E displayed `Kontoen er ledig` while Railway V3 worker logged five owned armed instances at 17:22 UTC, including E pilot `b800fdec` actual/target 0. Separate pilot `b6008676` is shown lower in screenshot at actual/target ~0.02; do NOT treat that as evidence of E ownership. | PR candidate changes **only UI/read model**: canonical V3 registry + ownership take precedence, registered E gets its own runtime/authority panel and Fleet link, V2 tab cannot offer a V3-claimed account, any conflicting authority fails closed. Regression tests cover V3 with no legacy enrollment, wrongly classified old strategy, double-owner and empty account. Railway deploy SHA remains unverified; no live account/config/position altered. |
| Hunter + Rabid Dog V3 LIVE catalogue | **#792 MERGED `055ed54a` with full green GitHub CI (2026-10-21); NOT RAILWAY DEPLOYED**. Hunter original SHADOW impulse/exhaustion policy and Rabid Dog price-change hysteresis are exposed as separate V3 strategies on exact tradable Saxo Tech100 UIC 4912 1s bid/ask. Durable per-instance JSON state survives worker restarts; quote gaps fail closed (Rabid explicitly requests FLAT after feed recovery). One Saxo minimum tranche, no 0.02 direct netting; V3 existing exact account ownership, broker precheck/cost, budget, reservation and CLOSE→confirmed FLAT→fresh OPEN protect orders. Rabid Dog limited to 16 shadow signal changes + 24 durable V3 order intents/hour with reductions always permitted. No auto-arming or instance change. | Railway `connect_service_source` for worker `main` attempted post-merge 2026-10-21 and returned **`Deploys have been paused temporarily`**. Do not claim LIVE deploy or filled trades. After Railway resumes: deploy worker **and web** from same GitHub main, verify exact SHA and service health; check quote density, 1s timing, exact account positions/locks/margin; THEN user explicitly chooses and arms one bounded account per strategy. Prospective cost-adjusted PAPER/LIVE attribution required; SHADOW results do not establish LIVE profitability. |
| HyperVigilant Chase 10s LIVE | **Merged [#775](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/775)** (`4a9c5717`), CI green, five Railway app services SUCCESS; real LIVE catalog FAST/FILTERED, no automatic arming | Check continuous genuine 1s BBO on exact Tech100 UIC + decision/close/reconcile/open timestamps; use separately bounded account only after explicit user selection |
| HyperVigilant direct reversals | V3 target changes LONG↔SHORT immediately on 10s impulse; execution is guarded CLOSE → Saxo FLAT reconciliation → fresh-signal OPEN | No atomic opposite-side netting and no guaranteed 10s Saxo fill; report actual latency/failures |
| Tech100 2m late-reversal audit (2026-10-21 12:28 Oslo) | Saxo 1m screenshot showed rebound from ~12:15, first blue buy marker near 12:28. Railway V3 worker f3e65462 (historically Hvelvet; verify current mapping) maintained `actual=-0.01,target=-0.01` from 10:10–10:27 UTC, first `target=+0.01` at 10:28:05, submitted CLOSE Buy 0.01 at 10:28:06, confirmed FLAT 10:28:17, submitted OPEN Buy 0.01 at 10:28:36, confirmed `+0.01` 10:28:45. Another instance b6008676 OPEN Buy 0.01 at 10:29:07. This is **late decision**, not predominantly Saxo transmission lag. HyperChase b800fdec remained target/actual zero during observed window (LIVE arming should not be inferred from this alone). | Determine current V3 strategy key for f3 from live config before changing model. Test price-first early exit/early reversal versus current 2m behavior prospectively with spreads/whipsaw costs. This PR adds only per-minute deduplicated `SIGNAL_TRACE` (actionable raw target, approved target, decision key and reason; no extra Saxo/AI). Do not auto-change active strategies. |
| HyperChase LIVE audit (2026-10-21) | Read-only worker logs: one HyperChase LIVE instance was cycling but `volatility-pause data_ok=False` because safety 1m bars were not loaded; operator disabled LIVE and the last exact observed Saxo position/target were both `0`. **Fix #780 merged and CI green**: 1m safety bars are loaded separately, cached per minute; 10s BBO entry/exit signals and Saxo reconciliation path unchanged. | **NOT DEPLOYED/NOT LIVE**: Railway API rejected worker source reconnect on 2026-10-21 with `Deploys have been paused temporarily`. Wait for Railway deploys to resume, verify deployed SHA and runtime safety evidence, then recheck account ownership, order state and explicit arming before LIVE. |
| HyperChase E sparse trades audit (2026-10-21 ~16:55 Oslo) | User's Tech100-E shows LIVE ON, FAST, 10 trades/24h, +0 P/L. Railway worker repeated `b800fdec` READY/actual 0/target 0 and MANAGING through ~14:42–14:57 UTC, no HyperChase order in inspected window. Stream probes for exact Tech100 UIC 4912 are `STREAMING`, but latest reported Saxo quote typically ~5–20 seconds old at minute probes; chart refresh 1000ms is not the same as genuine 1s BBO. Current 10s LIVE requires >=9 samples within 10s, <=5s age, max 3s gap, 9–10s reference, price move above cost/noise threshold. Root cause remains unconfirmed without action counts; 10 UI trades is not broker-reconciled. | This PR adds bounded once-minute `hyper chase LIVE GATE_SUMMARY` of unmodified strategy WAIT actions and safety veto counts, no new DB/Saxo/AI calls or strategy changes. **Current Railway production is still pre-#780/#782 until verified deployed; do not infer new code from GitHub merge.** Inspect actual UIC-4912 quote density and WAIT reason breakdown post-deploy. Distinguish long slow trends from 10s impulses. |
| HyperChase 1s input diagnostics | **#782 merged, CI green, NOT DEPLOYED:** bounded read-only BBO quote-quality probe measures genuine 60s samples, spread, max gaps, age and qualifying 10s windows independently of LIVE arming. | After Railway resumes, deploy worker from fresh main, inspect `hyper chase BBO QUALITY` once-minute logs for the exact Tech100 UIC. No automatic arming on deployment; do not claim 10s fills until actual Saxo timestamps are reconciled. |
| HyperVigilant PAPER | Merged [#774](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/774) (FAST/FILTERED) on prospective Saxo BBO in Strategilab v2 | Compare PAPER signal-to-next-quote delay, quote density and net after costs; do not infer Saxo fills |
| Strategilab v2 | Isolated historical multi-replay, Saxo cost/account overlays (#771); 18 V3 replay routes and chart scrubbing (#772); bounded AI error handling (#773); quote-based HyperChase PAPER (#774) | Check model/replay coverage and costs against real account/product data; maintain historical replay vs prospective PAPER vs LIVE evidence separation |
| Project continuity | #777 merged with green CI; GitHub Actions successfully updated `docs/PROJECT_CHANGELOG.md` on `main` at bot commit `a7501fd9` (2026-10-21). In Railway production all five app services have watch patterns: include `**`, exclude `/PROJECT_STATE.md` and `/docs/PROJECT_CHANGELOG.md`. | Verified: #778 docs-only merge `c7e22742` and resulting journal bot commit `53462b54` were `SKIPPED` by Railway on all five services; the Git journal still advanced. Recheck future runtime code deploys normally; bot journal never asserts LIVE readiness |
| V3 LIVE strategies | LIVE route additions merged for rhythm (#753/#755), MACD setups (#765/#766) and HyperChase (#775). Catalog presence is not per-account arming or broker success | Verify exact catalog-to-runtime mapping, live safeguards, instance assignment and broker evidence before changing any account |
| Account-level outcomes | NAV + strategy epochs and Saxo/EOD/TWR collection paths merged (#749–#752, #757–#758); Strategilab v2 account performance UI merged (#771). Code presence does not establish complete broker-reconciled history or causal attribution | Validate real Saxo snapshots and freshness, cash-flow/FX/fee handling, effective-time strategy joins and P&L consistency before ranking LIVE strategies |
| Railway CPU/DB cost audit 2026-10-21 | Measured 6h means: stream 1.108, Postgres 1.093, worker 0.550 vCPU; Postgres RAM 2.52GB. Old V2 research loops consumed repeated historical scans (up to 50–100k per market, 30–60s). Separate Lab AI PAPER loops had limits 80/480 calls/day (caps, not measured actual calls). | **#784 merged, green CI; NOT DEPLOYED**: legacy V2 research loops and Lab technical/context LLM PAPER loops default OFF with explicit env flags to reenable; freshness history diagnostics bounded 15m/20 rows. LIVE controls, Saxo telemetry, and V3 AI manager preserved. Compare after actual Railway deploy. |
| Stream registry/Saxo auxiliary scans | Local subscription check every 15s previously also invoked Saxo open-position discovery, futures rollover and historical seed on each poll. | **#786 merged, green CI; NOT DEPLOYED**: keep 15s DB subscriptions responsive, throttle auxiliary GET/history checks to 300s after startup (min60, env `PRICEGAUGER_RUNTIME_DISCOVERY_SECONDS`). Existing position/risk and account truth unaffected. |
| PostgreSQL storage footprint | Measured 24h Postgres RAM 2.48GB mean, CPU 1.07vCPU mean, disk ~11.74→11.95GB (about +210MB). Cause/table breakdown not yet known. | **#788 merged, green CI; NOT DEPLOYED**: read-only `pg_stat_user_tables` top-12 size/index/dead-row estimate once per 12h on telemetry sidecar. Review production output before archiving; no deletion or DB maintenance initiated. |
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

### Historical operational checkpoint (2026-10-21 UTC)

- **Delivered:** quote-driven HyperChase FAST/FILTERED LIVE in normal V3 chooser (#775), continuous prospectively sampled 1s PAPER experiment (#774), guarded close→broker-flat→fresh-quote open; no account enabled by deployment.
- **Validated:** GitHub CI for #775 green; Railway all five app services deployed merge SHA `4a9c5717` SUCCESS. This verifies delivery, not ≤10s broker execution.
- **Next action:** measure per-UIC `lsim_hyper_quotes_1s` sample gaps, quote age and true BBO freshness; run limited prospective PAPER comparison, then, only with explicitly selected small LIVE account, check ORDER/PENDING/RECONCILED timestamps, margin and fees. Any missing data means do not open automatically.
- **Synchronization:** update this file in each substantive PR; the Git journal is now verified to update automatically after a merge, but documents only commit provenance. Recheck bot writes and Railway watch-path behavior if either is reconfigured.

