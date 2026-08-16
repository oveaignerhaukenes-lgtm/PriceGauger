# ContextSnapshotV2

## Purpose

`ContextSnapshotV2` is the public output contract of the PriceGauger Context bounded context.
It separates semantic / holistic evidence processing from the deterministic Technical Core.

The Context Engine may internally use Telegram, broader news, GDELT, historical analogues,
LLM interpretation and later user-curated evidence. None of those implementation details are
part of the Technical Core contract.

## Authority boundary

The Context bounded context may:

- ingest and classify semantic evidence;
- deduplicate and cluster events;
- score novelty, source quality, confidence and contextual risk;
- maintain rolling semantic regime state;
- publish immutable `ContextSnapshotV2` values.

It must not:

- consume Technical Core output in order to decide what semantic evidence means;
- emit BUY / SELL execution authority;
- read or mutate AutoTrader execution state;
- write Technical Core state as a side effect of persisting context;
- call the legacy Information State / Decision State / Recommendation chain from the v2 persistence boundary.

Technical and Context outputs meet only in a higher composition layer.

## Provenance and personalisation foundation

Every evidence reference declares a source scope:

- `GLOBAL_SHARED`: shared evidence such as broad news, GDELT or common Telegram sources;
- `USER_SCOPED`: evidence belonging to a user-specific context universe.

`USER_SCOPED` evidence requires a `user_scope_id`. This is intentionally a foundation only.
AP2 does not implement Telegram login, forwarding, sliders or user profiles.

`source_kind` and semantic dimension names are open strings rather than closed enums. This
allows later sources and world-model dimensions to be introduced without changing the shape
of the public contract.

## Material-change semantics

Raw ingestion may occur frequently. Canonical semantic snapshots must not be persisted merely
because a polling loop ran again.

`state_fingerprint` is computed from semantic state and deliberately excludes `snapshot_id`
and `as_of`. It includes freshness state, coverage anchors, provenance, target assessments,
regime and summary. Therefore:

- identical semantic state at a later poll has the same fingerprint;
- a real semantic change has a new fingerprint;
- crossing a freshness boundary is material;
- a runtime adapter can persist only when `materially_changed_v2(...)` is true.

`as_of` remains part of immutable snapshot identity. Two observations made at different times
are distinct snapshot objects even when they represent the same semantic state, while the
fingerprint allows the runtime to avoid storing the redundant one.

## Contract shape

The contract is deliberately layered:

- `ContextEvidenceRefV2` — provenance and source ownership;
- `ContextDimensionV2` — extensible semantic dimensions;
- `ContextTargetStateV2` — target / market-level contextual state;
- `ContextSnapshotV2` — immutable public snapshot and state fingerprint.

`directional_bias` is contextual directional pressure in `[-1, 1]`, not a trading action.
Confidence, novelty and event risk are bounded in `[0, 1]`.

## Deferred work

Not part of AP2:

- adapting the current Telegram Flow / News Context engines into this contract;
- context persistence tables or runtime cutover;
- Holistic Composer weighting;
- learned Technical-vs-Context weights;
- manual mix sliders;
- Telegram user authentication / forwarded-message workflows;
- human hypothesis / worldview learning;
- retiring legacy state runtime.

Those are follow-on bounded capabilities after this contract is reviewed and stable.
