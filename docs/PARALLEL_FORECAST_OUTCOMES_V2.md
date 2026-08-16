# Parallel Forecast Outcomes v2

This capability resolves paired `TECH_ONLY` and `TECH_CONTEXT` forecast experiments against one shared realized market path.

## Invariants

- One `outcome_key` represents one market/as-of/horizon target.
- Both candidates are evaluated against exactly the same frozen reference price, terminal price, maturity timestamp and realized return.
- Active-market-time semantics are reused from `forecast_outcome_evaluation_v2`; long closures and provider gaps do not consume horizon time.
- No partial outcome is persisted before the horizon has matured.
- The objective realized outcome is immutable once stored.
- Candidate scores remain separate so absolute error, signed error, direction hit and interval coverage can be compared directly.

## Persistence

`pg_v2_parallel_forecast_outcomes` owns the single objective realized result per `outcome_key`.

`pg_v2_parallel_forecast_scores` owns one immutable score row per candidate kind for that same outcome.

This separation prevents Context changes from creating different market truth for otherwise identical forecast targets.

## Out of scope

- learned weighting or automatic recipe changes;
- LLM retrospective analysis;
- user sliders or hypotheses;
- UI changes;
- legacy retirement;
- AutoTrader/execution authority.
