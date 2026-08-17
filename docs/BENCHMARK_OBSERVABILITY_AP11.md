# AP11 — Benchmark observability and blind manual preview

AP11 exposes the paired TECH_ONLY vs TECH_CONTEXT benchmark in PriceGauger without changing canonical forecasts or introducing learning.

## Benchmark surface

The UI reads the AP10 benchmark read model and shows fully paired sample size, MAE, directional hit rate, interval hit rate and Context win/tie/loss counts by market and horizon. Small samples remain explicit; the UI does not infer statistical significance.

## Manual mix preview

The slider is a pure linear interpolation between the already-produced `TECH_ONLY` and fixed `TECH_CONTEXT` candidates from one stored parallel experiment:

`preview = (1 - mix) * TECH_ONLY + mix * TECH_CONTEXT`

The same interpolation is applied to lower and upper return bounds. `0%` therefore means TECH_ONLY and `100%` means the current fixed TECH_CONTEXT candidate.

This is deliberately not labelled as a pure semantic/Context forecast. ContextSnapshotV2 currently carries semantic state rather than an independently calibrated return forecast, so pretending otherwise would conflate unlike quantities.

## Authority boundary

Manual preview:
- is read-only;
- is not persisted;
- does not alter canonical Technical, Context, Composer or benchmark outputs;
- does not train or calibrate anything;
- does not influence AutoTrader or execution.

Per-source exposure/composition/identity/learning policy controls are deferred to AP12.
