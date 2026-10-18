# Verified Saxo futures family recovery — NGU6 → broker front (2026-10-18)

On deployed PR #741 the read-only Saxo GET returned 28 currently
visible ContractFutures candidates for Natural Gas. The first 12 all
pointed to **PrimaryListing 51202678**; that row is **NGX6**,
"Henry Hub Natural Gas - Nov 2026", exchange **NYMEX**.
Old registered instrument is **NGU6**, old UIC **50419383**.
The archived old UIC is no longer returned by broker reference search.

## No fuzzy substitution
Name/ticker/expiry similarity alone is NOT enough to write the collection
registry. The new recovery requires, ALL from Saxo itself:

- Previously installed old UIC's real \`instrument_details\`, including
  exact Uic/ContractFutures/Symbol, positive GroupId, ExchangeId,
  CurrencyCode, ContractSize and description family.
- Exact standardized symbol root (e.g. NGU6→NGX6), matching *complete*
  product family prefix, asset type, exchange and group across at least
  two independent futures summaries. Any conflicting GroupId or
  PrimaryListing vetoes recovery.
- The same single, positive broker \`PrimaryListing\` from this family,
  present as one exact candidate summary.
- A fresh independent broker GET of the candidate's \`instrument_details\`,
  with matching same Uic/asset type/product family/root/exchange/group,
  currency and contract size, \`IsTradable=True\`, expiry >1 day away.
- Failing/missing fields => NO recovery. Diagnostic list remains available.

Only on successful independent proof, adapter enriches a *read-only*
old details object with the new broker-authored PrimaryListing. The
pre-existing \`futures_rollover_v1\` then performs its own candidate GET
and active/expiry validation followed by atomic audited collection
subscription change. NO LIVE V2 or V3 order/position/strategy/risk,
account instrument authority or historical data is modified.
Previous candles stay tied to the old immutable instrument; new
candles to the new one with a rollover marker.

### Verification
- GitHub CI and regression fixtures for good broker proof and
  contradicted GroupId/exchange/currency/size/ticker/expiry/summary.
- Railway logs may show \`Saxo futures family VERIFIED...\` and
  \`Futures collection rollover...\` only after every validation passes.
- After deploy verify subscribed new UIC, price/chart event recovery
  during valid market hours (weekend closure does not imply a broken
  contract), and no change to four active Tech100 V3 traders.
- If old reference details lack reliable group/exchange/contract size
  or other identity evidence, **do not switch**. Repair must then wait
  for additional official Saxo continuous-futures-space metadata or
  explicit reviewed mapping; don't infer by name.
