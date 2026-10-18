# Natural Gas Saxo diagnostic: exact-series front GET (2026-10-18)

After #745, broker-verified rollover remained blocked (no silent switch).
The metadata probe showed old NGU6 ContractFutures UIC 50419383 with
NYMEX, USD, ContractSize 10000 and a missing old GroupId; public search
returned 28 different natural-gas related rows. The diagnostic incorrectly
formed its PrimaryListing consensus over *all* rows rather than the
exact source family, returning broker_primary=None and skipping a useful
read-only front DETAILS GET.

Now restrict ONLY the diagnostic candidate subset to broker rows with:
exact ContractFutures type, standardized NG symbol root, full source
product description family "Henry Hub Natural Gas", and old NYMEX
ExchangeId. The metadata log can then report Saxo's group-shared
PrimaryListing and fetch the candidate's independently returned public
instrument details, without any order, collection switch or database
mutation from this diagnostic. The separate strict rollover verification
remains fail-closed.

Find result under `Saxo futures family evidence READ_ONLY` in Railway
stream logs after deploy. If old/new contract size, currency, type,
group, IsTradable or expiry disagree, existing collection identity
must be retained. No LIVE V2/V3 execution paths are changed.