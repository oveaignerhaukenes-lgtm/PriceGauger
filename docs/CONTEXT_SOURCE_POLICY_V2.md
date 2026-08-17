# Context Source Policy v2

AP12 establishes policy metadata for Context sources without changing Context Engine scoring or introducing learning.

Each source has four independent controls:

- `exposure_enabled`: the source may be observed/fetched and surfaced diagnostically.
- `composition_enabled`: the source may contribute to a composed Context state.
- `identity_enabled`: the source is considered part of a user's persistent personalized worldview.
- `learning_enabled`: observations involving the source are eligible for future learning datasets.

These controls are intentionally independent. For example, a source may be exposed for trial use without being part of composition or identity; a source may be composition-enabled while learning is disabled; and future shadow-evaluation may permit learning while composition is disabled.

Unknown/new sources default conservatively to exposure on and composition/identity/learning off. Existing production sources are not changed by AP12 because no runtime consumes these policies yet. A later capability must seed or migrate explicit policies before using them to gate Context production.

User-scoped source identity includes `user_scope_id`, so the same Telegram channel can carry different policies for different users without changing the ContextSnapshotV2 contract.

## Authority boundary

AP12 does not:

- alter Telegram/News/GDELT ingestion;
- filter or reweight ContextSnapshotV2;
- modify Holistic Composer;
- train, calibrate, or tune any model;
- persist manual preview slider choices;
- affect Technical Core or AutoTrader.
