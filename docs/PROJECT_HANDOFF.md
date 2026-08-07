# PriceGauger handoff

## Current operational goal

PriceGauger is a live paper-analysis system. Its production path is:

`Telegram -> semantic filter -> per-post AI scoring -> event clusters -> Information State -> technical state -> Decision State -> recommendation -> outcome tracking`

The worker and Streamlit web service share PostgreSQL on Railway. Saxo prices and instrument configuration are live. Instrument metadata is versioned in `config/saxo_instruments.json`; do not restore `SAXO_INSTRUMENTS_JSON` unless a temporary environment override is intentionally needed.

## Production services

- `pricegauger-web`: Streamlit UI.
- `pricegauger-worker`: continuous Telegram, context, state and outcome processing.
- PostgreSQL: authoritative shared state.
- GitHub `main`: Railway deployment source.

Required secrets remain in Railway: `DATABASE_URL`, `OPENAI_API_KEY`, Saxo application credentials and Saxo token configuration. Never commit secrets.

## State ownership

- `TelegramFlowStore`: scored posts and aggregate flow snapshots.
- `NewsContextStore`: persisted rolling 1h/4h/12h/24h/7d geopolitical context.
- `StateRuntimeStore`: Information State, technical market states, Decision State, contributions and alerts.
- `AnalysisStatusStore`: user-visible status for every worker stage.
- `SignalOutcomeStore`: realized outcome tracking.

News Context uses the same source posts as Telegram Flow. It may set regime-level context fields (conflict regime, narrative saturation, confirmation quality and physical supply risk), but it must not add a second directional market impulse. Telegram Flow and market interpretations remain the only directional news contribution.

## Safe development workflow

1. Start from fresh `main` in `PRICEGAUGER-STABLE`.
2. Create a feature branch; never develop directly on `main`.
3. Keep changes scoped to a single production capability.
4. Run targeted tests and the full suite.
5. Open a draft PR, inspect the exact diff, then merge.
6. Verify both Railway deploys and one complete worker cycle.

## Acceptance check after the News Context deployment

1. Railway web and worker deploy successfully from the merged commit.
2. Oversikt shows `Nyhetskontekst` as complete (or a clear failed/skipped state), never indefinitely running.
3. Nyhetsmotor loads the latest persisted worker assessment without a manual button click.
4. A new context snapshot is stored when new source posts arrive or the 15-minute context heartbeat is due.
5. A context API failure leaves the last valid context available and does not stop technical analysis, Decision State, recommendations or outcome tracking.
6. Information State contains `context_as_of` and `context_engine_version`.

## Deliberately deferred work

- US 10Y instrument selection.
- Automatic futures contract rolling.
- Historical forecast graph and uncertainty bands.
- Backtesting, calibration and proof of recommendation value.
- Full risk sizing and final `NO TRADE` policy.
- Cross-market integration without duplicated evidence.

Do not expand these items while stabilizing the live pipeline. The next high-value phase is observation and calibration from stored forecasts and outcomes, not adding more UI or signals.
