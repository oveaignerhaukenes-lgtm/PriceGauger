# Context v2 runtime persistence boundary

This capability establishes canonical persistence for `ContextSnapshotV2` semantic state.

## Rules

- Raw Telegram/news evidence may update at high frequency.
- A canonical context snapshot is appended only when `state_fingerprint` changes.
- Poll timestamps and prose-only summary changes therefore do not create canonical rows.
- Freshness transitions are material state changes and are persisted.
- Freshness policy is applied after semantic adaptation and before persistence.
- Context persistence owns `context_v2_*` storage and may later move to a separate physical database behind the same store contract.

## Authority boundary

This runtime/store does not:

- invoke an LLM or regenerate semantic interpretation;
- read Technical Core;
- compose Technical + Context;
- invoke legacy Information/Decision/Recommendation runtime;
- issue trading recommendations or execution actions.

Wiring the existing Telegram/News worker to publish through this boundary is intentionally deferred to the next bounded capability so this persistence/freshness primitive can be reviewed independently.
