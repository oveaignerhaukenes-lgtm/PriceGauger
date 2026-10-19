# PriceGauger Saxo official account P/L and EOD performance · 2026-10-19

Supersedes the conjecture that an account's five-minute \`TotalValue\` delta
is true trading profit. Profit comparisons use Saxo's own historical
performance and separately tracked intraday account balance.

## Source and accounting semantics
- Saxo LIVE \`hist/v4/performance/timeseries\` reads each distinct account
  using **both exact \`AccountKey\` and \`ClientKey\`**, date window, and
  limited \`FieldGroups\`:
  \`Balance_AccountValue\`, \`Balance_AccountBalance\`,
  \`Balance_CashTransfer\`, \`Balance_SecurityTransfer\`,
  \`TimeWeighted_Accumulated\`. Sparse/missing values stay NULL.
  \`TimeWeighted.Accumulated[].Value\` is a FRACTION, convert to percent
  only in UI (multiply by 100).
- Saxo LIVE \`hist/v4/performance/summary\` supplies broker-computed
  \`AccumulatedProfitLoss\` for an explicit account and requested
  date window, if available. It is recorded as
  \`SAXO_REPORTED_ACCOUNT_PNL\` with \`LastTradeDay\` and actual period.
  Values aren't reconstructed from trade count or account-value delta.
- Saxo performance is processed **end of day**, not in realtime.
  Saxo's performance calculations include costs to open/maintain/close,
  currency conversion P/L and income from corporate actions. No attempt
  is made to double-subtract current open P/L or costs from this source.
- Historical EOD records use \`pg_saxo_account_perf_daily_v1\` and
  \`pg_saxo_account_perf_summary_v1\`, preserved independently from
  the 5-minute \`pg_saxo_account_truth_v1\` snapshots.
  Refresh/update of past rows uses the latest official Saxo calculation,
  no interpolation or guessed zeros.
- Collection is launched in the **independent Saxo telemetry thread**
  once daily when successful, hourly retry when not. Accounts without
  \`ClientKey\`, invalid account identity, missing currencies or broker
  errors are marked failed without leaking IDs or amounts.
- Analyse → Kontostatistikk shows the official broker-reported monetary
  P/L for each account, its requested reporting period and last trade
  date, and separate historical TWR/AccountValue. Intraday equity and
  contextual trader/market correlation remain independent below it.

## What this proves vs does not
**Proves:** account-level Saxo-calculated EOD money performance when source
has matching account context, a valid numeric \`AccumulatedProfitLoss\`,
and verified period bounds. Does not infer a return from raw equity delta.

**Does not prove:** which specific V3 strategy caused account-level P/L
when the account also had manual/V2/other-instrument trades or capital
flows; exact per-trade fees, funding or intra-bar stop slippage; real-time
profit while market is open; EOD metrics for unreported dates. The P/L
should NEVER be retroactively assigned to today's currently chosen
strategy without a complete transaction and position lifecycle.
Any other-currency account stays in its own currency; do not sum NOK+USD.

## Needed next for full trade attribution
- Account-scoped GET hist/v1/transactions with all pages, booking IDs,
  booked currency/amount, \`TransactionType\`, \`FundingSubType\`, and
  exact V3 broker-order IDs; include manual V2 and other products as
  explicitly "not attributed".
- Join reliable per-account Saxo P/L with exact strategy ownership and
  LIVE config history, booked FX/funding, market condition at execution
  and fill timestamps. Use causal event-time joins and label gaps.
- Calculate per-strategy after-cost P/L only on fully reconciled periods.
  Make AI reports/rankings consume this one broker ledger and abstain
  on incomplete data.

Saxo reference:
https://www.developer.saxo/openapi/referencedocs/hist/v4/performance/get__hist__timeseries
https://www.developer.saxo/openapi/referencedocs/hist/v4/performance/get__hist__summary
https://www.developer.saxo/openapi/learn/performance

Safety: **GET-only**, no changes to LIVE arming, strategy, account,
execution locks, broker orders or deposit/withdrawal configuration.
