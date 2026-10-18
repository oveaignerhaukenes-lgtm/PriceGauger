# Saxo NGU6→NGX6: independent summary group verification (2026-10-18)

Actual Saxo REF responses retrieved from Railway post-PR #746:

OLD expired `NGU6`, UIC 50419383: ContractFutures, Henry Hub Natural Gas Sep 2026, NYMEX, USD, ContractSize 10000, GroupId **omitted**.
NEW current `NGX6`, UIC 51202678: ContractFutures, Henry Hub Natural Gas Nov 2026, NYMEX, USD, ContractSize 10000, IsTradable=True, Expiry 2026-10-28, GroupId **also omitted** in per-UIC DETAILS.
Broker `ref/v1/instruments` SUMMARY gave ≥12 independent same-family contracts in NYMEX, every one with `GroupId=39074`, `PrimaryListing=51202678`. Exactly one summary row has that UIC. These match both old and new instrument details where fields exist.

Previous verifier correctly rejected missing GroupId from new DETAILS even though multiple independent broker SUMMARY rows proved the group. The ONLY change in this PR is that missing group from per-UIC candidate DETAILS can be supplied by unanimous broker summary consensus. If present, candidate DETAILS GroupId must still agree. All other checks on old/new UIC, ContractFutures, standardized symbol root, full product family, NYMEX, USD, ContractSize, independent new IsTradable and future expiry remain mandatory and fail-closed.

Existing audited atomic collection-subscription rollover is the only possible mutation. No change to LIVE V2/V3 trading instrument, Saxo order handling, accounts, positions, risk policy or historical bars.

Verification requires actual production log `Saxo futures family VERIFIED` and `Futures collection rollover market=Natural Gas` and then registry stream UIC 51202678. Even after successful collection switch, market-closed Sunday may delay fresh quote confirmation until trading resumes.