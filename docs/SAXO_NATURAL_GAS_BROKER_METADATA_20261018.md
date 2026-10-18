# Saxo Natural Gas blocked lineage: safe metadata evidence (2026-10-18)

PR #743 found 28 broker-listed current Natural Gas futures, including NGX6 UIC 51202678 on NYMEX, but did not authoritatively validate continuity with old UIC 50419383. Automatic collection rollover was correctly blocked. LIVE orders/positions untouched.

When the broker-verified family check cannot pass, log ONLY public instrument metadata for the old and broker-reported front UIC, plus summary GroupId / ExchangeId / PrimaryListing from the first four broker rows. This diagnostic performs at most one additional Saxo REF DETAILS GET, within the existing at-most-120s collection-only rollover cadence. No API POST or subscription mutation follows from these logs.

After deploy inspect `Saxo futures family evidence READ_ONLY` and determine the exact missing/mismatched field. Any future collection-source switch must retain the full fail-closed proof requirements (old/new symbol root, GroupId, exchange, currency, contract size, broker shared PrimaryListing, current tradable non-expired successor). Never auto-switch on ticker similarity alone.