# Spring Trade Engine

Spring Trade Engine is a bounded PriceGauger research/runtime context for modelling event-driven market motion as a potentially damped, regime-switching oscillator.

## Boundary

The engine may read canonical market data and optional context adapters, and may persist its own observational/model state. It has **no Saxo execution authority** and must not import or call AutoTrader OPEN/CLOSE execution paths.

The intended hierarchy is:

- `domain/` — state, episodes and regime concepts
- `observers/` — model-light measurements from market data
- `models/` — oscillator, equilibrium and regime-shift models
- `inputs/` — adapters for Technical Core, Telegram/news, cross-market, positioning/liquidity
- `persistence/` — dedicated Spring tables and stores
- `runtime/` — long-running observer/coordinator processes
- `research/` — calibration, diagnostics and backtests
- `contracts/` — outputs exposed to the rest of PriceGauger

The first bounded capability is deliberately narrower: a blind, price-only observer that records primitive spring-relevant measurements from canonical 1m bars. It does not trade and it does not yet claim that a damped oscillator is present.

## First observer

For each subscribed canonical instrument the observer records:

- blind equilibrium estimate (EWMA)
- price displacement from that equilibrium
- 1m velocity and acceleration proxies
- realized return volatility
- average intrabar range volatility
- shock z-score
- an energy proxy
- simple turning state

Future oscillator estimates such as period, damping ratio, oscillator confidence and context-adjusted equilibrium are explicit nullable fields in the contract so later models can be added without changing execution code.

## Railway

`railway.spring.toml` is a dedicated service configuration. A future Railway service can point at the same PriceGauger repo and PostgreSQL database while running Spring Trade Engine in a separate process from the stream/execution worker.

The service is observational only. Production deployment is optional until we explicitly choose to start collecting continuously.
