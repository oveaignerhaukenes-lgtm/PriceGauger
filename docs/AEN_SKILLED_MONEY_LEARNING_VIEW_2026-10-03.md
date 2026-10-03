# Skilled Money learning view — 2026-10-03

## Purpose
A read-only learning surface for understanding market participants and the mechanisms by which their constraints and incentives can become order flow and price movement.

## Hard boundary
This surface is intentionally disconnected from AutoTrader V2/V3, execution authority, strategy targets, reconciliation, persistent learning logs, and prediction. It must not become an execution input implicitly.

## Mental model
Read three layers together:
1. Technical regime — trend, volatility, momentum, correlation, liquidity, term structure.
2. World/news regime — growth, inflation, rates, energy, geopolitics, corporate and policy events.
3. Actor regime — plausible marginal buyers/sellers and the mandates, hedges, risk limits, rebalancing rules or policy objectives that can turn information into flow.

## Actor map
Initial categories: CTA/trend, discretionary macro/hedge funds, options dealers/market makers, vol-control/risk parity, pensions/long-only, passive/ETF, corporate hedgers, central banks/public sector, retail.

## Epistemic rule
Actor activity is frequently latent. The UI must distinguish observed data from inferred mechanism. Never state a particular actor caused a move unless there is direct evidence; otherwise label it hypothesis/inference.

## Retrospective chain
world/event -> priced expectations -> affected actors -> changed constraints/incentives -> order flow -> liquidity/market making -> price response

## Future visualizations
Only add visualizations when a real data source exists. Useful families include positioning/flow timelines, options/gamma structure, volatility/risk-control pressure, cross-asset response, rebalancing calendars, reserve/central-bank flows, and event-to-price retrospectives. Avoid a synthetic 'smart money score'.
