# Workspace Composer v2

This capability connects the deterministic Technical Core to optional cached refinement layers without cutting over production runtime.

The workspace is an in-memory snapshot for one market/as-of state. It owns the frozen Technical Core state, one or more frozen technical baseline forecasts, and cached layer outputs tied to an input fingerprint.

The target interaction model is:

`load canonical data -> build Technical Core once -> build baseline forecasts once -> run enabled expensive layers once -> cache outputs -> recompose recipes quickly`

A recipe may enable zero or more cached refinement layers. Technical-only composition must reproduce the frozen baseline exactly. Enabling a layer may adjust the composed return and uncertainty, but must not mutate the Technical Core state or technical baseline.

Cached layer outputs are rejected when their input fingerprint does not match the current workspace. This makes a new market-data snapshot a natural invalidation boundary: new relevant bars produce a new Technical Core state and therefore a new workspace fingerprint.

Technical Interpreter is the first supported refinement adapter. It converts its structured technical-only interpretation into the generic layer-output contract used by the composer. Future cross-market, regime and context layers should use the same boundary rather than bypassing the composer.

This capability remains runtime-agnostic. It does not read PostgreSQL directly, call an LLM, change existing pages, or alter trading/execution behavior. Persistence adapters and UI/runtime cutover remain separate bounded capabilities.
