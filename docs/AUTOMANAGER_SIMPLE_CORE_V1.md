# AutoManager Simple Core v1

Normal TradingDesk control plane:

- BUY / SELL set an explicit user target through the ordinary AutoManager execution lifecycle.
- AutoManager is either ON or OFF for the exact Saxo product.
- A single strategy selector controls the active LIVE strategy.
- When AutoManager is ON, an observed exact Saxo position is automatically adopted as managed basis; there is no separate user confirmation step.
- AUTO entry mode is the normal mode. Separate re-entry approval/arming is not part of the primary UI.
- Shadow models are independent persisted research series and are not configured when enabling AutoManager.

Hard execution correctness remains mandatory and is not a UI choice: exact account/UIC/AssetType identity, one LIVE controller, no pyramiding, no competing working order, CLOSE -> confirmed FLAT -> OPEN, final Saxo precheck, durable attempt before POST, and no blind retry after uncertain submit.

Accounting is asynchronous to execution. Once the exact Saxo product is confirmed FLAT after an accepted/reconciled PG close, realized-P/L reconciliation must not block the next valid OPEN. The ledger catches up independently; sizing uses the latest settled pilot equity available at submit time.
