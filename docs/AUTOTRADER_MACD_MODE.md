# AutoTrader MACD 30m mode

This bounded capability adds the first non-manual AutoTrader mode as a dry-run signal layer in TradingDesk.

## Behaviour

- Uses PriceGauger canonical 1m bars and existing TradingDesk resampling.
- Evaluates MACD on closed 30m candles using the existing TradingDesk indicator implementation.
- Bullish crossover creates one `Buy` position intent for the configured step amount.
- Bearish crossover creates one `Sell` position intent for the configured step amount.
- Remaining above or below the signal line does not create repeated intents.
- Each crossover receives a stable event key so later execution can persist/idempotently claim it.

## Safety boundary

This version does **not** send orders. It deliberately stops before Saxo execution because authoritative position reconciliation, persisted processed-event state, restart recovery and duplicate-action protection have not yet been added to the automatic path.

The existing SIM-only trading adapter and manual confirmation path are unchanged.

The intended next bounded capability is to connect these intents to persisted SIM execution state only after reconciliation/idempotency is in place.
