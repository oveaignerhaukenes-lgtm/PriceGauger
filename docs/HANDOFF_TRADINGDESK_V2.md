# Handoff — TradingDesk v2

## Mission

Own the human trading cockpit. TradingDesk should let the user inspect one selected market/instrument, understand the active PriceGauger analysis, choose a tradable Saxo product, size a position, and initiate explicit manual buy/sell actions through AutoTrader.

TradingDesk is not the execution engine and must never bypass AutoTrader guardrails.

## Architectural position

```text
PriceGauger analysis / forecasts
        ↓
Visualization + selected market
        ↓
TradingDesk
        ↓
AutoTrader validation / sizing / precheck / confirmation
        ↓
Saxo SIM (initially)
```

## First user-facing capability

The first trading capability is deliberately narrow: manually buy or sell the instrument/market currently being followed. The user initiates the action explicitly. AutoTrader performs server-side validation, Saxo precheck, product sizing, and confirmation before submission.

No automatic entry/strategy logic belongs in this first capability.

## What TradingDesk should show

- selected PriceGauger market and canonical instrument identity;
- live price/chart and selected technical indicators;
- v2 technical baseline forecast and optional selected refinement layers;
- concise technical/context explanation with clear provenance;
- available Saxo products for the selected market;
- product details relevant to risk and sizing;
- estimated exposure, leverage/knockout/stop implications where available;
- current position/execution state when supplied by AutoTrader;
- clear manual BUY / SELL entry controls and order preview;
- explicit confirmation state and failure/precheck messages.

## Analysis consumption

TradingDesk consumes PriceGauger outputs; it must not duplicate Technical Core or context-layer logic. Prefer reusable read models/workspace objects from the v2 analysis path.

The user should be able to see which recipe/layers are active before making a decision. A forecast should never be presented as if it includes context that is actually disabled.

## Instrument/product separation

PriceGauger's market/instrument identity and the Saxo product used to express a trade are related but distinct. TradingDesk owns the interaction for choosing among valid products; it must not collapse product-specific risk into the market-level forecast.

## Safety and execution boundary

TradingDesk must not call Saxo order placement directly. It sends a structured execution request to AutoTrader. AutoTrader owns acceptance/rejection, sizing constraints, precheck, confirmation, and final submission.

Initial operation remains SIM-only until the separate AutoTrader rollout explicitly changes that policy.

## AI companion direction

A future investor/trading companion may sit alongside TradingDesk and explain analysis, watch positions, discuss strategy, or propose actions. It should consume the same explicit PriceGauger information channels and emit structured proposals. It does not gain direct authority to bypass AutoTrader.

Human-readable reasoning can be shown in the frontend, but structured decision/provenance records should remain the backend source of truth.

## Working protocol

Start from fresh `main`, one bounded capability per branch/PR. Preserve the existing page concept and components where possible. Keep trading controls explicit and test UI source/contract boundaries. Coordinate product/execution semantics with AutoTrader rather than reimplementing them.

## Immediate next priorities

1. Align TradingDesk's selected market/instrument with the dynamic v2 instrument registry.
2. Embed the reusable v2 forecast/layer visualization from the graph thread.
3. Ensure product selection maps cleanly from market/instrument to Saxo candidates.
4. Harden order preview and manual execution request creation.
5. Display AutoTrader precheck/confirmation/errors clearly.
6. Add position state and position-management surfaces only after AutoTrader exposes stable contracts.

## Out of scope

Do not place orders directly, implement autonomous strategy entry, define database schema, or change analysis weights. TradingDesk is the human-facing orchestration surface between PriceGauger insight and AutoTrader execution.
