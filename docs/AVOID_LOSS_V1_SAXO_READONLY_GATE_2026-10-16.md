# Unngå tap V1 — Saxo read-only evidence gate (2026-10-16)

Status: **SAFE TO MERGE GET-ONLY; NOT LIVE-READY**. Pull-request based on main after #725.
This adds no strategy registration, worker watch, account arming, live orders,
position alteration, precheck POST, or automatic execution.

## Code
- \`autotrader_v3_live_saxo_v1.py\`: a strictly account-scoped GET of individual
  Saxo PositionBase+PositionView with unique PositionId and rejection of
  incomplete pagination or duplicate positions. Existing order audit GET
  additionally exposes returned PositionId and FilledAmount. Existing
  LIVE execution code is unchanged.
- \`autotrader_v3_avoid_loss_readiness_v1.py\`: bounded, redacted snapshot
  of account currency, exact net+individual positions, position status,
  NOK P/L and cost *field presence*, reliability, and quote timestamp.
  It cannot return LIVE_READY: no real initial-margin proof, order-fill
  reconciliation, accrued financing or successful CLOSE->FLAT verification.
- \`saxo_avoid_loss_readonly_probe_v1.py\`: an **operator invoked only**
  CLI for an explicit Saxo account and instrument. It prints status/reason
  codes only; no P/L, account ID, PositionId or tokens. It never POSTs.
- Regression tests use a fake broker that raises if an order/precheck is
  attempted, plus Saxo endpoint/account/PositionId/partial evidence checks.

## How to collect REAL read-only evidence
Run manually in an already authorized and trusted runtime where the existing
Saxo OpenAPI read access is configured; do not paste AccountId or tokens in
GitHub issues, chat, terminal recordings or CI logs:

\`\`\`bash
python saxo_avoid_loss_readonly_probe_v1.py --account-id "$SAXO_ACCOUNT_ID" --uic 4912 --asset-type CfdOnIndex
\`\`\`

The command does **not** select an account automatically. It will report
\`FLAT_OBSERVED\`, \`POSITION_FIELDS_OBSERVED\` or \`BLOCKED\` with
fixed safe reason codes. Successful field observation is **NOT** permission
to enable or merge the LIVE strategy; a FLAT account cannot prove P/L fields
for an open position. Operator must separately verify account ownership,
available margin, tradeability and realistic minimum size.

The code does NOT itself execute the command on Railway (the connector does
not offer a container exec action). Never treat fixture tests or CI as
evidence of a real broker fill.

## Broker contract cautions
- Saxo official \`GET /port/v1/positions\` examples show PositionId,
  PositionBase.Amount, PositionView.P/L in base currency and
  TradeCostsTotalInBaseCurrency, but omit optional CurrentPriceLastTraded.
  Without a fresh timestamp within 10 seconds the diagnostic fails closed.
- \`POST /trade/v2/orders/precheck\` is documented with Personal:Read, but
  is **not called by this tool**. Saxo's sample margin impact Currency is
  USD despite other amounts denominated differently. Treat a NOK
  initial-margin anchor as **UNVERIFIED**, not inferred by applying the
  \`InstrumentToAccountConversionRate\` to an unrelated currency.
- \`TradeCostsTotalInBaseCurrency\` is described as opening costs plus
  realized/unrealized closing costs. That alone does not establish all
  financing, FX or account NAV effects. Double counting remains a risk.
- An old/existing open position is NOT a valid starting position for this
  strategy: its frozen entry-time margin and order audit are absent.

## Additional blocked gates before real LIVE
1. Obtain *authorized* real sanitized evidence on an appropriately isolated
   FLAT account, with later read-only evidence from a newly confirmed
   minimal entry (only after separate explicit LIVE approval).
2. Validate actual Saxo precheck margin currency and **frozen incremental
   margin in NOK** vs starting account margin, and full costs / financing.
3. Confirm Status FinalFill + SubStatus Confirmed, exact OrderId/PositionId
   and filled quantity, including partial-fill and unknown/timeouts.
4. Prove CLOSE->broker-confirmed FLAT with durable V3 order guard and
   per-instance stop memory across restarts, gaps and market closure.
5. Bound the time spent in the Saxo data/exit path without starving the
   four existing LIVE strategy workers. Demonstrate correct UNPROTECTED
   handling with alerts and account safety.
6. Only then authorize an isolated low-risk LIVE trial; strategy activation
   is always separate from merging research code.

## References
https://www.developer.saxo/openapi/referencedocs/port/v1/positions/get__port
https://www.developer.saxo/openapi/referencedocs/port/v1/positions/get__port__me/schema-positiondynamic
https://www.developer.saxo/openapi/referencedocs/trade/v2/orders/post__trade__precheck
