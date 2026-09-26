# Hunter v1 — price impulse shadow

Hunter consumes Saxo bid/ask updates for `USNAS100.I` (UIC 4912). The streaming
service runs it in **shadow** and logs `Hunter SHADOW` transitions. No strategy
enrollment, Saxo order submission, netting, or 0.01 live sizing is connected.

## Causal policy

- A move of at least eight points within eight seconds, also at least four
  current spreads, starts LONG or SHORT from FLAT. A spread above five points
  blocks entry.
- A held impulse tracks its best observed midprice. After at least three
  seconds without a new extreme, a pullback of at least eight percent of the
  observed impulse (minimum 1.5 points) requests FLAT. There is no direct
  reversal.
- After a three-second cooldown, a pullback of **less than 15 percent of the
  observed impulse** may resume the same direction only after price exceeds
  the former extreme by more than the current spread. A deeper pullback
  invalidates that continuation; a fresh impulse is then required. This
  prevents buying a lower high. All pivots use prices available at the time;
  the first lower-low short is deferred until it can be tested independently.
- Stale or unordered quotes cannot trigger a transition. The model outputs a
  *desired target*, not evidence of a broker fill. A separate execution layer
  must reconcile its actual position, including after disconnects.

Thresholds are initial hypotheses, **not optimized or validated**. Midprice
signals are not executable bid/ask fills. The current production store retains
minute bars, not a complete one-second quote history. Before giving Hunter
live authority, persist timestamped bid/ask samples, replay on separate days
with actual spread and measured submission/fill latency, validate Saxo minimum
size and netting, cap live exposure and change frequency, and verify watchdog
responses to unknown fills and stream loss. Do not backtest this seconds-level
policy using minute OHLC bars.
