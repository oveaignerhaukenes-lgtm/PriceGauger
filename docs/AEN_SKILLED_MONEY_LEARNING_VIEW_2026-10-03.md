# Skilled Money learning view — 2026-10-03

## Purpose
A research/learning surface for understanding market participants and the mechanisms by which their constraints and incentives can become order flow and price movement.

## Hard boundary
This surface is intentionally disconnected from AutoTrader V2/V3, execution authority, strategy targets and reconciliation. It must not become an execution input implicitly.

Compact research persistence is intentional: Skilled Money stores a watchlist, selected market events, T0 analysis snapshots and append-only later revisions. It does **not** continuously archive raw ticks/order books or scrape every watched market into a second market-data lake.

## Event-driven workflow
1. Search a provider such as Saxo and bind the provider instrument to a generic `canonical_market` identity.
2. Add only markets that are worth following to the Skilled Money watchlist.
3. Create a manual event when the user asks «what happened in this move?»; this is the first practical workflow and does not require a detector.
4. Preserve the original T0 record.
5. Append later revisions when positioning, flow, options, holdings or official data becomes available.
6. After the manual workflow has been tested in practice, an automatic event detector may create cards only for materially relevant moves. It should not create continuous snapshots.

The canonical market identity is deliberately separate from Saxo UIC/AssetType so CME, ETF, options, macro and other provider bindings can later describe the same market.

## Mental model
Read three layers together:
1. Technical regime — trend, volatility, momentum, correlation, liquidity, term structure.
2. World/news regime — growth, inflation, rates, energy, geopolitics, corporate and policy events.
3. Actor regime — plausible marginal buyers/sellers and the mandates, hedges, risk limits, rebalancing rules or policy objectives that can turn information into flow.

## Actor map
Initial categories: CTA/trend, discretionary macro/hedge funds, options dealers/market makers, vol-control/risk parity, pensions/long-only, passive/ETF, corporate hedgers, central banks/public sector, retail.

## Epistemic rule
Actor activity is frequently latent. The UI must distinguish observed data from inferred mechanism. Never state a particular actor caused a move unless there is direct evidence; otherwise label it hypothesis/inference.

Snapshot revisions distinguish `OBSERVED`, `INFERRED`, `CONFIRMED`, `WEAKENED` and `REFUTED`. Later information appends a revision rather than rewriting what was known at T0.

## Retrospective chain
world/event -> priced expectations -> affected actors -> changed constraints/incentives -> order flow -> liquidity/market making -> price response

## Future visualizations
Only add visualizations when a real data source exists. Useful families include positioning/flow timelines, options/gamma structure, volatility/risk-control pressure, cross-asset response, rebalancing calendars, reserve/central-bank flows, and event-to-price retrospectives. Avoid a synthetic 'smart money score'.
