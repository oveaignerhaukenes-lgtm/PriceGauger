# Live-Sim Lab v1 — bounded forward experiments

## Intent

Dedicated research-only engine for comparing up to 100 **simultaneous** strategy configurations on **actual future canonical closed 1-minute bars**. A separate Railway service must be configured to run `live_sim_lab_worker_v1.py`; the existing LIVE worker and Saxo paths are untouched.

## Four lab questions

1. Which base/technical modifier combinations improve forward, cost-adjusted return versus same-period controls?
2. Which additions or revisions are justified by observed failure modes?
3. Which NEW strategy/modifier hypotheses should be handed to the PriceGauger architect for implementation?
4. Which approaches work under which technically classified regimes? Persist causal, per-strategy regime-attributed outcomes so later research can develop a detector.

## V1 boundary

- The lab seeds **72** locked variants on the first subscribed Tech100 instrument: 2 *lab-native* strategy styles (sticky / fast-exit), 2 signal periods (2m/5m), 3 regime periods (10m/15m/30m), 3 modifiers (none, whipsaw pause, adverse impulse exit), 2 fixed exposure levels (0.5 / 1.0 normalized NAV).
- These are **lab-native MACD approximations, not production-identical Aen#2/#2.1 implementations**. Promotion requires parity testing against canonical production decision logs, especially R/S sticky semantics and fills.
- `lsim_feature_cursors` shares incremental MACD and causal technical regime calculations by exact instrument. Initially 1100 prior closed bars are used **only to warm indicators**. No historical paper profits are included.
- Every proposal is made from a CLOSED signal bar and filled at the NEXT closed canonical 1-minute bar's open. The system uses future data only when that future bar actually arrives. It does not use tick or bid/ask quotes.
- Virtual NAV uses exposure-normalized returns. Fixed 5bps turnover friction is only a provisional substitute for spread/slippage; financing, broker lot contract value, margin availability and market impact are not yet modelled. Do not interpret NAV results as executable Saxo P&L.
- Each variant has an immutable configuration/version/started_at and unique id. A future modification MUST get a new id. `lsim_regime_memory` attributes next-minute paper NAV changes to the **previous bar's** already-known regime (no ex-post regime tagging).
- Classification: warmup, range, trend, impulsive motion, whipsaw and relative high volatility, derived exclusively from returns available at each point.
- `lsim_daily_reports` stores frozen descriptive 20:00 Europe/Oslo snapshots. A **single optional daily AI interpretation** is attempted when at least six variants have observations and at least one variant has 30 already-attributed bars. The evidence contains matched modifier/control deltas plus regime memory; the prompt demands all four lab questions and explicit uncertainty. Set OPENAI_API_KEY and optionally OPENAI_MARKET_MODEL on the **lab worker only**. No key means data collection and factual snapshots continue with no AI cost. API attempts are claimed durably BEFORE requesting to prevent restart-induced repeat charges. Failed attempts are not retried automatically.
- The worker and the Streamlit Lab page share the existing PostgreSQL connection. Deploy only as a separate worker service (with DATABASE_URL) after CI, never start it in the LIVE worker loop.
- Without the dedicated worker, the UI displays an idle lab; it must not falsely claim experiments are active.

## Next milestones

1. Wire dedicated Railway `PriceGauger-LiveSimLab` service and shared DATABASE_URL. Check 1m receipt latency and 72-variant runtime.
2. Validate same-timeframe MACD parity against canonical indicators and verify exact execution timing, market closure gaps and idempotence in production observations. Resolve gaps and backfill contamination before publishing rankings.
3. Upgrade ledger to instrument-specific contract point value, quoted bid/ask spreads, slippage distribution, financing and margin normalization; expose realized vs marked NAV.
4. Add locked experiment enrollment/pause UI and distinct new-variant creation for controls/modifier ablations.
5. Calibrate the new bounded daily AI analyst; confirm sample-size caveats, matched controls, output quality and operational API cost. Proposed models must remain draft research with no automatic strategy mutations.
6. Holdout forward validation and multiple-comparison safeguards before strategy promotion.

## Parallel development

TradingDesk architect may change TradingDesk and graph components in a different branch. This lab branch owns `live_sim_lab_*`, `pages/0_Live_Sim_Lab.py`, the lab Railway config, docs and a single additive `navigation_config.py` line. Avoid changes to canonical LIVE V3 execution files.
