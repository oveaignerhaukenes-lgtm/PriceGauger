# Analyst Companion v2

## Purpose

Analyst Companion is an optional, session-scoped technical-analysis companion for a human who is actively following a market. It is deliberately separate from Technical Core, TradingDesk and AutoTrader.

The Companion does not own the forecast and does not execute trades. Technical Core remains the deterministic baseline. Companion observes the current persisted v2 technical state and canonical price history, preserves short session continuity, and produces concise analysis of what the technical setup may mean as it evolves.

## User semantics

- **Activate Companion** creates a new session bound to the currently selected market.
- **Companion active** means the session follows new persisted Technical Core snapshots for that market.
- **Ask Companion** asks a contextual technical-analysis question inside the active session.
- **End session** closes the session. A new activation starts a new continuity context.

A Companion session never silently follows the user to a different market.

## Data flow

`canonical price history + persisted Technical Core/read model -> deterministic level candidates -> Companion structured payload -> AI structured analysis -> concise frontend commentary`

The UI fragment may rerun frequently, but the AI provider is called for continuous analysis only when `view.as_of` changes. Re-rendering the same snapshot does not produce another analysis call.

## Grounding

Support/resistance levels are not free-form AI output. `derive_level_candidates_v2()` extracts deterministic candidate clusters from observed price history and labels them `S1..Sn` / `R1..Rn`. The model may reference only those IDs in structured state. Runtime validation rejects unknown or wrong-kind IDs.

This preserves a useful separation:

- software measures candidate price levels;
- AI interprets the context around those observed levels;
- the human decides what, if anything, to do with that analysis.

## Structured state

Each accepted analysis contains:

- directional context: bullish / bearish / neutral / mixed;
- breakout status: none / testing / breakout / retest / rejection / failed breakout;
- pullback classification: none / normal / profit taking / mean reversion / reversal risk / undetermined;
- squeeze risk: low / moderate / high / undetermined;
- watched support and resistance candidate IDs;
- confidence;
- concise `what_changed`;
- concise human commentary;
- observable watch conditions.

The prior accepted structured analysis is included in the next payload so `what_changed` can be genuinely incremental.

## Session continuity

Companion v1 intentionally stores its session in Streamlit session state rather than DB v2. The session keeps:

- market identity;
- activation time;
- last observed Technical Core snapshot;
- most recent structured analysis;
- a bounded recent turn history for questions and answers.

This is enough to validate the interaction model without introducing a persistence contract prematurely. Persistent Companion histories can be added later as a bounded DB capability if they prove useful.

## Hard boundaries

Companion has no execution surface. It receives no Saxo order client, AutoTrader command path, position size or order authority. Its provider prompt explicitly excludes buy/sell instructions, sizing, leverage instructions and orders.

Companion is also not a forecast layer in v1. Its analysis does not mutate the Technical Core baseline or workspace forecast. If later versions should influence a forecast recipe, that must be introduced as a separate explicit layer contract rather than by reusing the conversational Companion implicitly.

## Provider

`OpenAICompanionProviderV2` follows the repository's existing OpenAI Responses API pattern and requires strict JSON-schema output. `OPENAI_COMPANION_MODEL` may override the model; otherwise the existing market-model configuration is reused.

## Next likely evolution

A future Companion owner can improve deterministic level extraction, add event/change detection, enrich the technical input contract, improve prompts, or optionally introduce session persistence. Those changes should preserve the core invariants above and remain separate from execution authority.
