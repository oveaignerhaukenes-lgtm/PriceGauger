# PriceGauger handoff

## Current operational goal

PriceGauger v1 is a live paper-analysis system. Its production path is:

`Telegram -> semantic filter -> per-post AI scoring -> event clusters -> Information State -> technical state -> Decision State -> forecast snapshot -> recommendation -> outcome tracking`

The worker and Streamlit web service share PostgreSQL on Railway. Saxo prices and instrument configuration are live. Instrument metadata is versioned in `config/saxo_instruments.json`; do not restore `SAXO_INSTRUMENTS_JSON` unless a temporary environment override is intentionally needed.

The v1 Overview is intentionally a compact cockpit. Each market card presents the current analysis, recommendation and a forecast trajectory with realized history, a clear `now` boundary, base/bull/bear paths and an uncertainty fan. Forecasts are persisted so they can be compared with realized outcomes later rather than regenerated from current information.

## Production services

- `pricegauger-web`: Streamlit UI; reads persisted state and does not start the analysis pipeline when opened.
- `pricegauger-worker`: continuous Telegram, context, technical, state, forecast and outcome processing.
- PostgreSQL: authoritative shared state.
- GitHub `main`: Railway deployment source.
- GitHub Actions: compile + full pytest suite for development branches and pull requests.

Required secrets remain in Railway: `DATABASE_URL`, `OPENAI_API_KEY`, Saxo application credentials and Saxo token configuration. Never commit secrets.

## State ownership

- `TelegramFlowStore`: scored posts and aggregate flow snapshots.
- `NewsContextStore`: persisted rolling 1h/4h/12h/24h/7d geopolitical context.
- `StateRuntimeStore`: Information State, technical market states, Decision State, contributions and alerts.
- `ForecastStore`: immutable/persisted forecast snapshots tied to the exact Decision/Information/Technical state used at forecast time.
- `MarketHistoryStore`: coarse realized price history sourced from persisted technical states; forecast cards use active trading time so weekends/session gaps do not erase the comparison window.
- `AnalysisStatusStore`: user-visible status for every worker stage.
- `SignalOutcomeStore`: realized outcome tracking.

News Context uses the same source posts as Telegram Flow. It may set regime-level context fields (conflict regime, narrative saturation, confirmation quality and physical supply risk), but it must not add a second directional market impulse. Telegram Flow and market interpretations remain the only directional news contribution.

## v1 behavior and guardrails

- Worker failures degrade individual stages rather than stopping the whole cycle where practical.
- Missing/stale inputs must be visible; analysis continues with the information that is available.
- Forecast cards retain `PROVISIONAL`/`NO-TRADE` semantics while the movement model is uncalibrated.
- The current movement interval is an explicit deterministic baseline and is marked with `calibrated_move_model` as missing until outcome data supports empirical calibration.
- Forecast trajectory shapes are qualitative/operational (trend, range, squeeze, impulse-reversal), not minute-by-minute price claims.
- Realized history is neutral/dark; base path uses the market color; bull/bear are semantically color-coded; stale/closed-market price gaps are shown rather than drawn as false flat trading.

## Safe development workflow

1. Start from fresh `main`.
2. Create a feature/fix branch; never develop directly on `main`.
3. Keep changes scoped to a single production capability.
4. Run targeted tests and the full suite through GitHub Actions.
5. Open a draft PR, inspect the exact diff, then merge.
6. Verify Railway deploys and one complete worker cycle for production changes.

## v1 acceptance baseline

1. Web and worker deploy from the same merged `main` generation and share PostgreSQL.
2. Worker runs continuously; opening Overview only reads persisted state.
3. A failed source/stage is marked and does not unnecessarily prevent downstream analysis with remaining inputs.
4. Overview market cards show analysis, recommendation, horizon/move interval/confidence and forecast trajectory.
5. Forecast trajectory shows comparable realized active-market history on the left and forecast scenarios on the right; closed-market gaps remain visible.
6. Forecast snapshots persist the exact state references needed for later calibration and outcome comparison.
7. Outcome tracking continues to accumulate evidence for calibration.

## Post-v1 priorities

### v1.1 — interactive scenario workspace

- Open a market card into a detailed workspace.
- Toggle major analysis drivers on/off and generate a separate scenario forecast without rewriting the authoritative forecast.
- Add an AI discussion/prompt surface for user-supplied information, theories and counterfactuals.
- Preserve original vs modified scenario vs realized outcome for comparison.

### v1.2+ — follow / live thesis

- `Follow` a market/development as a persistent live thesis.
- Comment continuously on whether new news, prices and scheduled macro releases confirm, weaken or invalidate the thesis.
- Update the recommendation in relative terms such as hold/reduce/add/exit while keeping the evidence trail explicit.
- Add dedicated event handling for releases such as CPI, PPI and NFP with pre-event state and post-release reaction tracking.

## Deliberately deferred work

- US 10Y instrument selection.
- Automatic futures contract rolling.
- Backtesting, calibration and proof of recommendation value beyond the current stored-outcome baseline.
- Full risk sizing and final `NO TRADE` policy.
- Cross-market integration without duplicated evidence.
- Interactive scenario controls and live-thesis follow mode (post-v1 as described above).

The next high-value phase after v1 is observation and calibration from stored forecasts/outcomes. Avoid adding new signals merely to increase feature count before the existing forecast chain is measured.
