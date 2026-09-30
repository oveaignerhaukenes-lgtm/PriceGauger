# Architect 16 handoff - 2026-09-30

V3 has reached controlled Saxo LIVE execution. Production main includes PR 594, commit 98f76766a23d67a5544209ec40163f4fefd5eec4. Railway worker deployment 1cfe480c-bd41-4a67-96f9-c6ad6d5e0ce7 is SUCCESS. At handoff the first post-594 V3 cycle had not appeared yet because the worker was still in its ingest phase. Verify that cycle before declaring the sizing fix operationally complete.

## Runtime model
Strategy target -> exact Saxo account/product actual -> delta -> precheck and exposure cap -> one durable order -> fresh exact position verification. A mismatch waits without blind retry. Reversal goes through verified FLAT.

Core files: autotrader_v3_live_runtime_v1.py, autotrader_v3_live_saxo_v1.py, autotrader_v3_order_guard_v1.py, autotrader_v3_position_reconciliation_v1.py, autotrader_v3_execution_plan_v1.py.

## Work completed
PR 589 normalized order quantities with Decimal steps. PR 590 made V3 inventory/planning canonical in integer centilots, removing binary-float tails. Do not revert to float rounding.

PR 592 changed confirmed chart markers: AutoTrader executions are arrow-only with distinct colors; manual Saxo trades use arrow plus MANUAL text.

PR 593 made TradingDesk shared close/chart/pilot-status controls use the selected Saxo account boundary, avoiding product-wide ambiguity when V2 and V3 use the same UIC on different accounts. Files: tradingdesk_automanager_simple_v1.py, tradingdesk_automanage_panel_v2.py, tradingdesk_automanager_close_control_v1.py, tradingdesk_chart_trade_controls_v1.py, tradingdesk_pilot_status_panel_v1.py.

PR 593 also exposed safe V3 sizing validation reasons. Production then showed: actual=0, target=-0.01, delta=-0.01, then V3 exposure cap leaves less than Saxo minimum order amount.

PR 594 fixes that identified index-CFD sizing error. cap_open_add_amount_v3 had applied Saxo ContractSize/PriceToContractFactor as an additional amount multiplier. The V3 CfdOnIndex cap now uses executable price times FX for per-amount exposure while Saxo amount precision/minimum remains quantity authority. Files: autotrader_v3_live_sizing_v1.py and tests/test_autotrader_v3_live_sizing_v1.py. CI passed and Railway deployed.

## First task
Read the first V3 runtime cycle on deployment 1cfe480c-bd41-4a67-96f9-c6ad6d5e0ce7 and verify the old exposure-cap false positive is gone. If sizing still blocks, follow the specific diagnostic rather than bypassing the cap or precheck. Also verify TradingDesk no longer reports multiple controllers merely because V2 and V3 use the same product on separate accounts.

## Invariants
Keep exact account + UIC + AssetType binding, one unresolved durable order, fresh position verification, Saxo precheck, exposure cap, and FLAT-first reversal. Audit/orderactivities are diagnostics, not strategy input. Saxo position is actual-state truth; strategy target is desired-state truth. Unexpected external mutation while pending must block.

Before deliberately causing another real LIVE mutation, obtain renewed explicit user authorization.

## Next architecture work
After runtime stability, simplify V3 further and remove old audit reconciliation from the critical path only when tests prove no dependency. Then do the requested behavior-preserving folder reorganization toward autotrader/v3 with strategy, execution, broker and risk subfolders; autotrader/v2; and a small shared area. Do not combine the move with behavior changes.

Preserve: V2 and V3 may run simultaneously on different Saxo accounts; one account belongs to one engine; V3 config lives in its dedicated control surface; TradingDesk is compact operations; chart markers represent confirmed executions; budget times exposure_pct is the submission-time cap.

Working method: code -> tests -> PR -> poll CI -> fix -> merge -> Railway deploy -> inspect runtime. Include filenames in user summaries.
