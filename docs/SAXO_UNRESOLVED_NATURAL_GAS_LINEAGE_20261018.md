# Natural Gas Saxo unresolved contract — read-only evidence and bounded retry

After PR #740 production Saxo still reported:
- old subscribed UIC 50419383 / NGU6 no longer valid for price/chart;
- no exact old UIC row exposing a usable distinct PrimaryListing;
- no next futures contract could be resolved. Data collection NOT repaired.

This PR does NOT substitute a guessed Natural Gas futures UIC.

## Read-only evidence
When both exact-UIC+IncludeNonTradable and keyword+IncludeNonTradable Saxo
reference lookups fail to return an exact old-UIC PrimaryListing, the
second lookup emits one bounded log:
  \`Saxo expired-futures lineage UNRESOLVED ... broker_candidate_count=...
    first_candidates=[{uic,symbol,description,exchange,display_hint,primary}]\`
Only public instrument summaries of matching Saxo ContractFutures type are
logged (maximum 12); no accounts, tokens, Saxo positions or amounts.
There is **no** automatic selection based on name, exchange or symbol.

## Bounded collection-only check
The collection-data futures rollover check is now limited to 1 attempt
per 120 seconds per stream process, using an in-memory monotonic lock.
This prevents repeated failed reference-data requests and traceback
logging on every ~5-second registry refresh. First check after startup
still runs immediately; future opportunities retry automatically.
A newly available collection futures successor may be discovered at
most 120 seconds later. No Saxo LIVE trader/risk/watchdog/order operation
uses this throttle. Runtime market subscriptions, registry read, seeded
history and LIVE accounts are untouched.

## Next
Inspect actual broker candidate log after Railway deploy. A safe
recovery must establish the *same continuous futures space* as the old
Henry Hub NGU6 contract (not merely a similarly named gas product),
confirm non-expired tradable contract details and exchange/contract
identity and retain atomic rollover auditing. If lineage cannot be
proven from Saxo, retain UIC and fail closed; operator intervention
required. The historical collection interruption cannot be filled by
assuming prices.
