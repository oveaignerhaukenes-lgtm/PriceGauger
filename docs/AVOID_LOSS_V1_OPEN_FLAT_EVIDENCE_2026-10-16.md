# Unngå tap V1 — OPEN / FLAT broker provenance contract

Date: 2026-10-16. **Research-only, not a LIVE strategy.**

This pure module must never be mistaken for proof of actual Saxo broker fills.
Its scope is to reject mismatched data before persisting the immutable
initial margin or declaring a broker-confirmed flat lifecycle.

## What must match for a new OPEN
- Staged immutable preflight margin **in NOK** with exact account, Uic,
  asset type, 1 tranche and request key.
- Durable V3 order guard explicitly **RECONCILED** and broker OrderId known.
- Saxo \`GET /cs/v1/audit/orderactivities\` already scoped and matched to
  this exact AccountKey, OrderId, Uic and asset type by the GET-only adapter.
  Status \`FinalFill\`, SubStatus \`Confirmed\`, exact filled size, side,
  original individual \`PositionId\` all required; partial \`Fill\` rejected.
- Independently read sole individual \`PositionBase.Amount\`/status/account
  and exact account net signed inventory must agree with staged and filled
  amounts. Direction is from signed net inventory and durable Buy/Sell,
  **not** a nonexistent PositionStatic.OpeningDirection.
- Return a frozen \`ConfirmedPositionV1\` object. No broker POST, no DB
  writes, and no actual registration of the anchor is performed.

## What must match for confirmed FLAT
- An explicit caller-verified no-pending-order state.
- Both exact account+product Saxo net positions and individual positions
  read through separate scoped GETs are **empty**, not zero net with
  leftover individual positions.
- A missing response, pending/unknown order or a suspicious zero-net
  hedge fails closed. This is more conservative than observing net=0 once.
- Actual broker close order execution and timing STILL require verification
  on an expressly approved low-budget account and must not be inferred
  from the output of the pure function.

## Remaining LIVE gate
Real authorized broker read-only evidence; measured account-currency
margin and financing including full transaction costs; viable quote
timestamp/reliability; supervised minimum-position LIVE test on an
unowned FLAT account; exchange-closed/outage/restart/partial-order paths;
measured CLOSE->broker FLAT; fault isolation from the four active fleet
strategies.

Never merge the obsolete draft #721 wholesale: its worker/strategy routing
remains unverified. Use this pure module only from a future, guarded
integration built on latest main.

Saxo refs:
- https://www.developer.saxo/openapi/learn/audit-orderactivities
- https://www.developer.saxo/openapi/referencedocs/port/v1/positions/get__port
