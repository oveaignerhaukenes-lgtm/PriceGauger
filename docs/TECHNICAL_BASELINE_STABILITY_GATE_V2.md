# Technical Baseline Stability Gate v2

This gate defines the minimum conditions for treating the PriceGauger v2 technical baseline as a stable foundation for further contextual layers.

## Required invariants

1. Canonical 1m observations are the sole raw input to the v2 technical baseline.
2. Higher timeframes are derived through the canonical UTC resampling contract.
3. Missing minutes are never forward-filled into synthetic market observations.
4. The currently forming higher-timeframe bucket may participate in live analysis.
5. Repeating the same canonical input produces the same Technical Core state and technical baseline forecast.
6. TA-only composition is identity-preserving: with no enabled refinement layers, composed return and interval equal the Technical Core baseline.
7. Recipe identities are versioned and immutable.
8. Persisted state/forecast identities are restart-safe and idempotent.
9. Runtime health can distinguish HEALTHY, STALE, DEGRADED and NO_DATA.
10. The v2 UI is read-only and cannot trigger analysis, AI, provider, Saxo or trading side effects.
11. Technical Interpreter output is optional and cached separately; the deterministic baseline remains usable without AI.
12. Forecast outcomes are evaluated against realized canonical price paths without retroactively changing the forecast.

## Gate meaning

Passing this gate does not assert that the baseline is profitable or calibrated for every market. It asserts that it is deterministic, observable, falsifiable, versioned and safe to iterate on. Performance calibration belongs to the next phase and can compare TA-only against explicitly enabled refinement recipes without changing the meaning of historical forecasts.
