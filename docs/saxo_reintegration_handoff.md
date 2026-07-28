# Saxo reintegration handoff

This note is for reintegrating the Saxo work from `feature/combined-direct` into an earlier PriceGauger branch without importing the later event-pipeline architecture wholesale.

## Source and baseline

- Repository: `oveaignerhaukenes-lgtm/PriceGauger`
- Saxo source branch: `feature/combined-direct`
- Earlier structural baseline / merge base: `main` at `ac483b34c65ac11199c1f09433fdff8f3f1448f7`
- Original Saxo provider foundation commit: `7cab05029870347ca1435b050fc8025dd7aa3013`

The Saxo foundation commit is already part of the old baseline. The later OAuth, diagnostics and UI work exists in `feature/combined-direct`, mixed with unrelated architecture commits. Do **not** cherry-pick all 52 commits from that branch. Port the Saxo files selectively.

## Files to reintegrate

### Core authentication

1. `saxo_auth.py`
   - OAuth authorization URL and state generation.
   - Authorization-code exchange.
   - Atomic JSON token store.
   - Automatic access-token refresh.
   - Refresh-token expiry and reauthentication states.
   - SIM/live environment separation.
   - Default token paths: `data/saxo_tokens_sim.json` and `data/saxo_tokens_live.json`.

2. `saxo_auth_ui.py`
   - Streamlit OAuth connection UI.
   - Displays connection state and token expiry without exposing tokens.
   - Handles callback code/state and disconnect/reconnect flow.

### Market-data provider

3. `saxo_provider.py`
   - Start from the version on `feature/combined-direct`, not the old foundation version.
   - Important additions relative to commit `7cab050`:
     - `SaxoError` with explicit status codes.
     - Dynamic `access_token_getter` support.
     - Automatic refresh and one retry after HTTP 401.
     - Safe response parsing and typed provider errors.
     - `info_price()` support.
     - OAuth-first `configured_client()`, with static `SAXO_ACCESS_TOKEN` fallback.
     - Instrument expiry validation.
     - Explicit unsupported reasons: `TOKEN_MISSING`, `INSTRUMENT_MISSING`, `INSTRUMENT_EXPIRED`.

4. `market_data.py`
   - Port only the provider-fallback/diagnostic changes needed by the current branch.
   - Preserve the earlier branch's existing provider abstraction if it has diverged.
   - Intended provider order is Saxo first, then Yahoo fallback.
   - A Saxo entitlement/authentication failure must be visible as evidence, not silently converted into a Yahoo result.

5. `market_sync.py`
   - Optional but useful if the earlier branch needs a central live-data synchronization layer.
   - Review against the earlier architecture before copying; this file is not required for basic OAuth and chart retrieval.

### Diagnostics and UI

6. `saxo_diagnostics.py`
   - Normalizes InfoPrices states into:
     - `REALTIME`
     - `DELAYED_<N>MIN`
     - `NO_ACCESS`
     - `PRICE_AVAILABLE_DELAY_UNKNOWN`
     - `PRICE_UNAVAILABLE`
   - Separately diagnoses chart availability and age.
   - This distinction matters because SIM may allow chart bars while denying InfoPrices entitlement.

7. `pages/7_Saxo_OpenAPI.py`
   - Full Saxo test/diagnostic page.
   - Shows OAuth status, instrument discovery/details, InfoPrices status and charts.
   - Integrate its functionality into the earlier branch's navigation conventions rather than copying page numbering blindly.

### Tests

8. `tests/test_saxo_auth.py`
9. `tests/test_saxo_auth_ui.py`
10. `tests/test_saxo_diagnostics.py`
11. `tests/test_saxo_provider.py`
12. `tests/test_market_data_fallback.py`

Run these before reconnecting Saxo to Direct Technical.

## Required configuration

Secrets/environment variables:

```text
SAXO_APP_KEY
SAXO_APP_SECRET
SAXO_REDIRECT_URI
SAXO_ENVIRONMENT=sim
SAXO_TOKEN_PATH=data/saxo_tokens_sim.json   # optional override
SAXO_BASE_URL                                # optional override
SAXO_AUTH_BASE_URL                           # optional override
SAXO_INSTRUMENTS_JSON
```

Static-token compatibility remains available through:

```text
SAXO_ACCESS_TOKEN
```

OAuth should be preferred.

Token files must remain ignored by Git. Confirm `.gitignore` includes Saxo token JSON files.

## Instrument configuration

`SAXO_INSTRUMENTS_JSON` maps PriceGauger asset names to Saxo instruments, for example:

```json
{
  "Brent": {
    "uic": 0,
    "asset_type": "ContractFutures",
    "symbol": "...",
    "description": "...",
    "expiry": "...",
    "price_multiplier": 1.0
  },
  "Silver": {
    "uic": 0,
    "asset_type": "ContractFutures",
    "symbol": "...",
    "description": "...",
    "expiry": "...",
    "price_multiplier": 0.01
  }
}
```

Do not reuse placeholder UIC values. Use instrument discovery and verify the selected contract, expiry and price multiplier.

## Recommended integration sequence

1. Confirm the target branch and create an integration branch from it.
2. Copy `saxo_auth.py` and its tests.
3. Copy the OAuth-related changes from `saxo_provider.py`; resolve against the target branch's current `market_data.py` interface.
4. Copy `saxo_diagnostics.py` and tests.
5. Add `saxo_auth_ui.py` and adapt it to the target branch's Streamlit layout.
6. Add/adapt the Saxo OpenAPI page.
7. Configure SIM OAuth and verify token refresh.
8. Run instrument discovery and populate `SAXO_INSTRUMENTS_JSON`.
9. Verify charts independently for Brent, Silver, Gold and DXY.
10. Verify InfoPrices independently and display entitlement status correctly.
11. Only then reconnect `SaxoPriceProvider()` as first provider in Direct Technical, retaining Yahoo as explicit fallback.

## Acceptance criteria

The reintegration is complete when:

- OAuth login succeeds in SIM.
- Access tokens refresh automatically without manual replacement.
- Token material is never rendered or logged.
- Instrument search/details work.
- Chart data loads and normalizes OHLC values correctly.
- Silver's explicit multiplier is respected where required.
- The UI distinguishes `MARKET_CLOSED`, `NO_ACCESS`, `DELAYED`, `REALTIME`, and missing/invalid chart data.
- Direct Technical reports whether data came from Saxo or Yahoo.
- A Yahoo fallback does not hide the reason Saxo was unavailable.

## Known empirical result from the previous work

- SIM OAuth connected successfully.
- Automatic refresh worked.
- Instrument lookup worked.
- Chart endpoints returned usable bars.
- InfoPrices could return `NO_ACCESS`, likely due to SIM market-data entitlement. This must be treated as an entitlement state, not as a generic API failure.

## Commands for manual extraction

From a local clone, the safest starting point is to inspect or restore individual files from the source branch:

```bash
git show feature/combined-direct:saxo_auth.py > /tmp/saxo_auth.py
git show feature/combined-direct:saxo_auth_ui.py > /tmp/saxo_auth_ui.py
git show feature/combined-direct:saxo_diagnostics.py > /tmp/saxo_diagnostics.py
git show feature/combined-direct:saxo_provider.py > /tmp/saxo_provider.py
git show feature/combined-direct:pages/7_Saxo_OpenAPI.py > /tmp/7_Saxo_OpenAPI.py
```

For files that already exist on the target branch, use a three-way/manual merge rather than overwriting them wholesale:

```bash
git diff <target-branch>..feature/combined-direct -- saxo_provider.py market_data.py pages/2_Direct_Technical.py
```

The main conflict risk is architectural, not OAuth logic: `market_data.py`, Direct Technical and Streamlit page numbering/layout may differ on the earlier branch.
