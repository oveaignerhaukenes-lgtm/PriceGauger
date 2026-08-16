# Parallel Forecast Benchmark Read Model v2

AP10 adds a read-only observability layer over resolved paired forecast outcomes.

The read model only compares fully matched `TECH_ONLY` and `TECH_CONTEXT` scores that share the same `outcome_key`. It groups by market and horizon and exposes sample size, mean absolute error, directional hit rate, interval hit rate, deltas between candidates, and context win/tie/loss counts.

## Interpretation

- `mae_delta = TECH_CONTEXT_MAE - TECH_ONLY_MAE`; negative is better for Context.
- directional and interval hit-rate deltas are `TECH_CONTEXT - TECH_ONLY`; positive is better for Context.
- win/tie/loss is based only on paired absolute error for the exact same realized outcome.

This is descriptive observability only. It does not alter Composer weights, recipes, Context processing, Technical Core, AutoTrader, or execution authority. Small samples must remain visible as small samples; this layer does not infer statistical significance or promote model changes.
