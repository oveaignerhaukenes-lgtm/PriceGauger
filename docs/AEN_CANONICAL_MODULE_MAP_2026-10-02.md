# PriceGauger canonical module map — 2026-10-02

This map is the naming/retirement companion to `AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md`.
It records responsibility rather than filename generation numbers.

| Responsibility | Canonical module | Compatibility / presentation | Retirement status |
|---|---|---|---|
| Engine identity | `autotrader_engine_identity_v1.py` | shared UI may read it | canonical |
| Saxo account → engine ownership | `autotrader_engine_account_ownership_v1.py` | none | canonical |
| V2 operator LIVE authority | `autotrader_v2_control_plane_v1.py` | raw `autotrader_manage_control_v1.py` remains runtime primitive | control plane canonical; raw primitive not UI API |
| V3 operator LIVE/SIM authority | `autotrader_v3_control_plane_v1.py` | raw live/sim authority modules remain worker/recovery primitives | control plane canonical |
| V3 LIVE execution | `autotrader_v3_live_runtime_v1.py` | worker scheduler | canonical; do not refactor during live stabilization |
| V3 exact inventory ownership | assigned account + UIC + AssetType, reconciled by V3 runtime | Saxo inventory is source of truth | canonical |
| Durable order lock | currently `autotrader_v3_order_guard_v1.py` | also consumed by V2 pyramid adapter | behavior is shared; neutral rename/extraction deferred |
| Exact position reconciliation | currently `autotrader_v3_position_reconcile_v1.py` | also consumed by V2 pyramid adapter | behavior is shared; neutral rename/extraction deferred |
| V2 TradingDesk controls | `tradingdesk_automanager_simple_v1.py` | `tradingdesk_automanage_panel_v2.py` facade | active |
| AutoManage P/L pilot selection | `tradingdesk_automanage_read_model_v2.py` | facade | extracted from legacy 2026-10-02 |
| AutoManage activity timeline | `tradingdesk_automanage_activity_ui_v2.py` | facade | extracted from legacy 2026-10-02 |
| Old monolithic AutoManage panel | none | `tradingdesk_automanage_panel_legacy_v2.py` | deleted after caller/test migration |
| Heavy analysis labs | individual `tradingdesk_*_lab_v1.py` modules | lazy toggle in AutoManage P/L fragment | still shares page; computation is lazy |

## Boundary rules

- Operator UI must call the V2/V3 control plane, not raw authority setters.
- A LIVE enable transition must acquire the persistent account ownership boundary before authority is armed.
- A LIVE disable transition removes execution authority before releasing account ownership.
- V2 and V3 may own different Saxo accounts concurrently; dual-engine ownership of one account fails closed.
- Presentation/session state never establishes execution identity.
- Shared execution primitives may eventually receive neutral names, but this is a naming extraction only: no execution semantics should change during that migration.

## Next structural cuts

1. Finish routing remaining V2 operator authority mutations through `autotrader_v2_control_plane_v1.py` without changing worker/recovery primitives.
2. Separate heavy analysis rendering from the live TradingDesk page boundary.
3. Introduce a neutral name/facade for the durable order guard and exact reconciliation primitives currently named `v3` but intentionally shared by the V2 pyramid adapter.
4. Add canonical execution correlation/diagnostic timeline before further execution-core simplification.
