# Technical Core v2

Technical Core v2 is the deterministic control-group market model for PriceGauger v2.

It consumes already-loaded canonical market frames and produces an inspectable `TechnicalCoreState` plus a simple baseline forecast. No Telegram, macro, cross-market, regime or AI input is allowed into this baseline capability.

## Determinism

For the same canonical input frames and recipe version, Technical Core must return the same state and baseline forecast. This is the control group against which later layers are evaluated.

## Inputs

The first implementation deliberately reuses the existing deterministic calculations in `technical_analysis.py`: RSI 14, MACD 12/26/9, EMA 20/50, ATR 14, swing structure, support/resistance proximity and optional volume participation. The v2 core composes those outputs rather than duplicating indicator code.

## Multi-timeframe state

Preferred primary timeframe order is `30m -> 1h -> 15m -> 5m -> 4h -> 1m`. Available timeframe snapshots contribute to a weighted aggregate technical score. Missing timeframes are allowed and reduce confidence rather than causing invented data.

The state exposes trend, momentum, volatility, structure, normalized aggregate score, bounded confidence and underlying snapshots for auditability.

## Baseline forecast

The intentionally simple TA-only forecast derives direction, expected return, uncertainty bounds, confidence and a coarse path shape (`TREND_CONTINUATION`, `DRIFT`, or `MEAN_REVERTING_OR_RANGE`) from the technical state and requested horizon.

This is not the final forecast model. Later layers may refine bounded path properties, but must preserve the original technical baseline unchanged.

## Scope boundary

This capability does not persist v2 state to PostgreSQL, change current production forecast generation or pages, activate context layers, execute trades, or call an LLM. Persistence, forecast composition, UI exposure and AutoTrader consumption remain separate bounded capabilities.
