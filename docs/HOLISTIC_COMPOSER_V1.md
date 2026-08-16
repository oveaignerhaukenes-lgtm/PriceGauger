# Holistic Composer v1

Holistic Composer v1 is the first explicit meeting point between the independent Technical Core and Context bounded contexts.

## Inputs

The composer accepts only:

- one immutable `TechnicalBaselineForecast` produced by Technical Core v2;
- one canonical `ContextSnapshotV2` produced by Context Engine v2.

It does not fetch Telegram, news, price data, positions or account state itself. It does not call an LLM and it does not invoke legacy Decision/Recommendation runtime or execution.

## Composition rule

Technical Core remains the baseline authority. A Context target can refine the baseline only when the canonical Context snapshot is `FRESH` and contains a target matching the technical market.

v1 deliberately uses a fixed bounded rule rather than learned weights or user sliders. Directional context may shift expected return by at most a small fraction of the technical uncertainty scale. Novel event risk may widen uncertainty, but Context cannot replace the technical baseline.

Stale Context and missing target coverage remain visible in provenance but contribute zero adjustment.

## Provenance

Every holistic output records the Technical Core recipe/as-of and the Context snapshot id, semantic fingerprint, engine version, freshness, as-of and matched target. The original technical baseline is retained separately from the composed return.

This makes the first cross-domain composition auditable and creates a stable evaluation point before learned weighting is introduced.

## Out of scope

- LLM-based holistic reasoning;
- learned layer weights;
- user weighting sliders;
- legacy Decision/Recommendation retirement;
- persistence/runtime scheduling of holistic outputs;
- UI changes;
- AutoTrader or execution authority.
