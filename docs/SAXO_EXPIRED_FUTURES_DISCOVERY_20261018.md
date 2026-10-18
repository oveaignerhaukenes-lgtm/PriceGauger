# Expired Saxo futures UIC recovery (18 Oct 2026)

Observed: Natural Gas has a stale, expired 2026-09 contract \`NGU6\`,
UIC \`50419383\`, classified as \`ContractFutures\`. Saxo market-stream
GETs reject this UIC (HTTP 404: UIC not valid). Source logs also show
\`no next futures contract could be resolved\`. We MUST NOT guess a
replacement UIC or create an unrelated live trading instrument.

## Root cause / fix
The existing rollover discovery did a generic
\`GET ref/v1/instruments?Keywords=Natural Gas&AssetTypes=ContractFutures\`
with **no IncludeNonTradable**. Saxo's documented search may omit
non-tradable/expired products, exactly when an old UIC is needed to read
its broker-owned \`PrimaryListing\` (the next expiring instance).

Search instead:
1. \`GET ref/v1/instruments?Uics=<EXACT_OLD_UIC>&AssetTypes=ContractFutures&IncludeNonTradable=True\`.
2. If exact UIC lookup returns no trustworthy broker successor, fallback
   to existing keyword search but ALSO IncludeNonTradable=True.
3. In both cases ACCEPT ONLY the unique row whose \`Identifier\` equals
   the exact OLD UIC and \`AssetType\` equals the prior type, and that
   carries a DIFFERENT positive \`PrimaryListing\`.
4. The existing authoritative rollover then independently fetches
   Saxo details for the new UIC and checks tradability/expiry before
   performing the existing atomic, audited collection subscription change.
5. No response / unrelated candidates / Saxo failures => fail closed,
   preserve existing registry and LIVE execution identity.

This is a collection-data rollover only, NOT a modification to V3
LIVE execution, held positions, order routes, margin or user accounts.

Reference: Saxo REF/v1/instruments GET documents \`Uics\` and
\`IncludeNonTradable\`. The Saxo SummaryInfo schema documents
\`PrimaryListing\` as next expiring instance for expiring instruments.

## Verification
- Full GitHub CI.
- Production stream logs after Railway deploy: look for
  \`Futures rollover recovered broker PrimaryListing...\` and
  \`Futures collection rollover...\`.
- If old UIC cannot be found even with nontradable search, this
  patch cannot establish a safe new contract. Gather broker reference
  data (continuous futures space / original expiry lineage) before any
  manual subscription switch. Do NOT choose by \`NG\` symbol prefix alone.
