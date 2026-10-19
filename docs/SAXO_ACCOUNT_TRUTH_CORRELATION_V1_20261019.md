# PriceGauger account truth / account-strategy-market correlation v1

Priority: **CRITICAL**. Previous Fleet compared only currently open Saxo P/L,
not whether the trading accounts actually grew after execution. SIM ranking
cannot replace actual LIVE account NAV, financing, costs and transfers.

## Implemented
- **Broker first:** read Saxo LIVE \`GET port/v1/accounts/me\`, then one
  **account-key-scoped** \`GET port/v1/balances?AccountKey=...\` for **every**
  Saxo account, including those without a V3 instance (e.g. metal/storage).
  Verify returned account currency. \`TotalValue\` is mandatory and numeric;
  unreliable \`CalculationReliability\` is retained for diagnostics but NOT
  used as a verified return.
- **Durable:** immutable account snapshot each 5-minute UTC interval per
  account in \`pg_saxo_account_truth_v1\`. Records observed timestamp,
  account currency, \`TotalValue\`, \`CashBalance\`, unrealized margin P/L,
  financing accruals, not-yet-booked transactions, estimated cost to close,
  margin used/utilization, and Saxo reliability. Unknown fields remain NULL.
  No guessed FX exchange rates or synthetic balance history.
- **As-of strategy/market context:** immutable JSON for exact V3 instance,
  strategy key, timeframe, regime period, modifiers, LIVE arming, Saxo
  instrument UIC, canonical market and latest observed bar close with its
  *own timestamp*. Missing market data remains NULL. Context is snapshotted,
  not overwritten by the strategy currently selected today.
- **Process isolation:** the Telegram multi-worker launches a separate
  five-minute telemetry daemon thread with its own Saxo LIVE client,
  read timeouts capped to 5s per HTTP request. Collector catches failures,
  logs only sanitized counts/status, and NEVER calls order, precheck, DELETE,
  flags, strategy switches or any LIVE authority mutation. Existing fast
  V3 trading thread remains independent. No trader settings are changed.
- **Statistics:** Analyse → Kontostatistikk. Per-account actual Saxo value
  curve with source and reliability, account cash/margin/financing summary,
  timestamped V3 strategy and canonical market context, optional normalized
  market vs account-value visualization, and per-account reconciled
  V3 execution event records. Operators can trigger an additional
  **read-only GET** on demand if needed; automatic collection continues
  without an open browser tab.

## Crucial distinctions
**Observed**: change in Saxo \`TotalValue\`, inclusive of deposit/withdrawal,
FX, positions, interest, carrying costs and booking changes. This is NOT
necessarily trading profit.

**Unverified**: Actual NET result; remains NULL in report
(\`CASH_FLOWS_AND_BOOKED_COSTS_NOT_RECONCILED\`) until we ingest the
account-scoped Saxo transaction ledger and reconcile cash transfers,
booked charges, interest/funding, position proceeds, and daily account
performance. A synthetic P/L ranking is never emitted by this collector.
Broker-valued \`UnrealizedMarginProfitLoss\` is a *component*, and must
not be added to \`TotalValue\` (double-counting).

**Correlation**: contemporaneous strategy, execution, market data and
account value are observable. Attribution is **not** proven without checking
other instruments, manual trades, transfers, strategy switches, and
unreconciled orders. V2 and manual trading may exist on the same account.

**No historical overclaim:** 5-min observations begin when the collector
starts. Saxo historical account values (hist/v4 Performance), booked
cashflows (hist/v1 Transactions) and trade history can separately backfill
daily/transaction records, but must be integrated only after their raw
field schemas, pagination and account currency are validated.

## Next milestone (required before treating account changes as profit)
1. Read \`hist/v1/transactions\` and \`hist/v4/performance\`, with exact
   AccountKeys, all pages, date coverage and verified booking currencies.
2. Reconcile deposits, withdrawals, account transfers, CFD funding/fees,
   trade settlement and FX against account value; label unresolved periods.
3. Produce flow-adjusted NAV returns, realized+unrealized LIVE attribution,
   regime-conditional P/L, drawdowns and same-clock SIM vs LIVE basis.
4. Make daily/weekly AI reports and strategy ranks consume the **same**
   auditable account ledger, explicitly withholding recommendations when
   inputs are missing. No execution rights are granted to analytics.

Official Saxo references:
- https://www.developer.saxo/openapi/referencedocs/port/v1/balances/get__port
- https://www.developer.saxo/openapi/referencedocs/hist/v1/transactions/get__hist
- https://www.developer.saxo/openapi/learn/account-history

Safety: This PR is an observability change; account collector GET is not
an authority to place Saxo orders. Existing LIVE instances are unchanged.

## POST-deploy real Saxo balances diagnostic correction 2026-10-19

The initial deployed GET-only collector discovered 12 Saxo accounts, but
`port/v1/balances` requests all failed. The independent `hist/v4` collector
successfully stored official EOD series for 4 accounts. The fix scopes
balance queries with both the mandatory `AccountKey` and verified
`ClientKey` from the same account row, consistent with the public Saxo API
reference. All broker HTTP errors are aggregated into safe, non-identifying
`SAXO_BALANCES_HTTP_4xx/5xx` status codes; timeouts/auth errors also have
fixed categories. It never logs account IDs, raw responses or balances.
If the broker still rejects GETs, the HTTP status is required to distinguish
permissions from payload mismatch; no fallback to client-wide balances is
allowed because that would silently misattribute equity to an account.
