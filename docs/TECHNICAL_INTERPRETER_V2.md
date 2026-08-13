# Technical Interpreter v2

Technical Interpreter v2 is the narrow AI-facing layer immediately above the deterministic Technical Core.

It exists because static indicator weights are only a control-group approximation. The practical meaning of resistance, momentum, volume, volatility and structure depends on their interaction. The interpreter may reason about those interactions using ordinary technical-analysis principles, but it is deliberately denied external context.

## Allowed input

Only the already-computed Technical Core state and its underlying technical snapshots may be supplied to this layer.

Allowed examples include trend, EMA relationships, MACD, RSI, volatility, support/resistance proximity, swing structure and volume participation.

The layer must not receive news, Telegram, macro releases, cross-market state, regime interpretation, account/position state or execution information.

## Output contract

The interpreter returns structured bounded values suitable for persistence, evaluation and forecast composition:

- directional bias;
- continuation probability;
- mean-reversion probability;
- breakout probability;
- rejection probability;
- squeeze probability;
- confidence;
- explicit emphasis weights describing which technical facts mattered most;
- a concise human-readable explanation for the UI.

The human explanation is intentionally pedagogical: it should make it possible to understand why, for example, resistance was treated as weak because momentum and volume were expanding, or strong because participation and momentum were fading.

## Control group

The deterministic Technical Core remains unchanged and independently inspectable. Technical Interpreter output is an optional refinement layer and must be attributable to its own recipe/version.

This enables direct comparison of:

`deterministic TA`

against

`deterministic TA + Technical Interpreter`

and later against richer recipes that also enable regime, macro or semantic context.

## Scope

This capability defines the contract and validation boundary only. It does not yet choose an LLM provider, call an LLM in production, persist interpreter output, change the forecast UI, or affect AutoTrader execution.
