# Recovery from archived Saxo futures with missing old GroupId (2026-10-18)

Authoritative Railway READ-ONLY metadata:
- OLD: Saxo NGU6 UIC 50419383, ContractFutures, "Henry Hub Natural Gas - Sep 2026", NYMEX, USD, ContractSize 10000.0, expired 2026-08-27, **GroupId missing** (not conflicting, just NULL).
- NEW CANDIDATES: Broker ref/v1/instruments lists 28 Natural Gas futures; relevant NG family from Saxo is NYMEX, GroupId 39074, common broker PrimaryListing 51202678 (NGX6 / Henry Hub Nov 2026). Exact archived NGU6 summary is unavailable.
- Original strict proof required old GroupId and correctly refused a silent substitution.

## Minimal change
When old GroupId is missing, replace that one proof with at least **three independent Saxo reference entries** sharing exactly the archived UIC's externally verified symbol ROOT, Description family, AssetType and ExchangeId. All must report the same positive GroupId AND the same PrimaryListing, with one exact front row. Any contradiction/unknown => no switch. When old GroupId is present, matching remains mandatory.

Crucially, all *other* existing strict conditions are preserved: broker OLD exact details UIC, AssetType, Symbol, NYMEX ExchangeId, USD CurrencyCode, positive ContractSize; broker NEW independent DETAILS must match candidate UIC, matching symbol root, same exact product family/exchange/group/currency/contract size, IsTradable=True, non-expired. No ticker/name-only switch. All future broker reference GETs are collection-only and rate-limited via PR #741. Existing audited atomic collection rollover is the **only** mutation; V3 account instruments, LIVE trade routing and existing positions are never changed.

After deploy look for \`Saxo futures family VERIFIED old_uic=50419383 new_uic=51202678\` and \`Futures collection rollover market=Natural Gas...\`. Only if these are observed can historical 1m subscription become current. Real quotes may wait until Sunday/Monday market reopening. If proof still fails, no broker subscription should change and diagnostics remain available.
