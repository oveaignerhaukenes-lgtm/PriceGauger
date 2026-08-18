# AP15A — Overview semantic shell cutover to Context v2

Overview now consumes canonical `ContextSnapshotV2` for its semantic/news context and the existing v2 workspace for Technical Core cards.

## Consumer boundary

`context_overview_read_model_v2.py` projects only the public Context v2 contract. It does not import Telegram Flow, News Context internals, legacy Information State, Decision State, Recommendation, old forecast stores, an LLM, or execution state.

The Overview page therefore no longer uses `overview_service.load_overview()` to establish semantic or market authority. It renders:

- Context freshness, regime and summary from the latest canonical snapshot;
- per-target directional bias, confidence, novelty and event risk;
- Context evidence provenance pointers (source/scope/timestamps/tags);
- unchanged canonical v2 Technical Core/workspace forecast cards.

## What remains intentionally alive

The existing Telegram/News semantic engines still produce their internal Flow/News Context outputs and publish them into `ContextSnapshotV2`. The legacy `process_flow_snapshot -> Information State -> Decision State -> Recommendation` downstream still runs in `worker.py` for now, but Overview is no longer a consumer of it.

That downstream retirement is deliberately a separate AP15B capability. Keeping producer retirement separate from the final consumer cutover gives one clean rollback point and avoids changing semantic generation and presentation authority in the same PR.

Historical market-data adapters and realtime dual-write are also unchanged; they remain temporary AP13/AP14 migration seams until live v2 bar coverage is verified.
