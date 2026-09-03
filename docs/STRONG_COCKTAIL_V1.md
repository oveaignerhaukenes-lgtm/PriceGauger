# Strong Cocktail v1 — fast-event / slow-context shadow

Status: **SHADOW ONLY**. This document defines a measurement hypothesis, not execution authority.

## Why this exists

The first Cocktail Mode proved that sampling forming 5m/10m/15m/30m MACD on one canonical 1m clock removes candle-close latency. The NAS100 case on 2026-09-03 exposed a second problem: even a continuously sampled 5m or 10m MACD can be mathematically late relative to a fast price move.

Strong Cocktail therefore adds a true **1m MACD 12/26/9** timing layer. It does not replace the slower horizons. It changes their role.

Core principle:

> Price and 1m momentum detect the event; higher horizons qualify confidence instead of acting as sequential cross gates.

The design deliberately keeps the asymmetry from Cocktail Mode #1: it should take less evidence to leave exposure and go FLAT than to commit capital in the opposite direction.

## Common comparison clock

Strong Cocktail is compared directly with a deliberately simple control:

- **Strong Cocktail** — 1m event timing + direct price qualification + persisted 5/10/15/30m Cocktail context.
- **1m MACD flip control** — LONG on a contiguous bullish 1m MACD cross and SHORT on a contiguous bearish 1m MACD cross. No price filter, no slow-context filter, no whipsaw logic.

Both begin FLAT on the first persisted Cocktail Mode #1 sample and use the same subsequent observed price path. Historical crosses before that point are not replayed. This makes the pair a direct experiment rather than two curves with different start assumptions.

The 1m control is intentionally crude. Its purpose is to answer a hard question: does the additional Strong Cocktail logic add value beyond simply reacting faster?

There is no assumption that Strong Cocktail will win. The hypothesis is that it should capture more meaningful excursion while paying less whipsaw cost than the raw 1m control. The data decides.

## Strong Cocktail v1 evidence

### Fast event layer

Computed from canonical 1m bars:

- 1m MACD spread
- 1m MACD cross
- ATR-normalized 1m MACD spread velocity
- ATR-normalized 3-minute and 5-minute price displacement
- short path efficiency
- local 5-minute structure break

### Slow/context layer

Read from the already persisted Cocktail Mode #1 sample at the same canonical action time:

- forming 5m / 10m / 15m / 30m MACD spread
- activity z-score
- 1m range ratio
- 5m directional efficiency
- support/resistance break direction
- existing Cocktail shock evidence
- existing whipsaw classification
- data-gap flag

Strong Cocktail v1 does **not** wait for a 5m, 10m, 15m or 30m cross to grant ordinary entry authority. Those horizons are evidence about context.

## Decision semantics

### Exit / FLAT

When already exposed, Strong Cocktail may go FLAT before a formal 1m MACD cross when:

- price has moved materially against the position over the fast window, and
- 1m MACD spread velocity is moving in the same adverse direction.

A confirmed adverse 1m cross with adverse price direction also flattens.

This is the deliberately lower evidence threshold for risk removal.

### Normal entry

From FLAT, an ordinary entry requires:

- a contiguous 1m MACD cross,
- aligned 3-minute price direction,
- aligned 1m MACD velocity,
- at least one direct price/activity qualifier, and
- slow-horizon context that is not overwhelmingly opposed.

There is no requirement to wait for the next higher MACD cross.

### Strong event

A sufficiently large, efficient and price-confirmed 1m event can override opposing slow context. This is the shadow analogue of the abrupt NAS100 move that motivated the model.

### Whipsaw

If the existing Cocktail whipsaw detector is active, Strong Cocktail remains FLAT unless the fast event qualifies as a strong escape.

### Data gaps

Data gaps force Strong Cocktail FLAT. The simple 1m control does not fabricate a cross across a gap; it keeps its prior state until a later contiguous cross.

## P/L semantics

Both new curves are gross/no-spread shadow curves. Returns are applied on the common observed price path using the position held over the preceding interval; the state transition occurs at the newly observed 1m action point.

They do not write to the authoritative Saxo equity ledger.

## Execution boundary

Neither Strong Cocktail nor the 1m control is present in the LIVE execution-capable strategy catalog. This capability contains no Saxo order POST path, no OPEN/CLOSE request writer and no Product Admission authority.

Promotion beyond shadow requires a separate bounded capability with explicit tests and the normal lifecycle:

`signal -> CLOSE -> confirmed Saxo FLAT -> settled P/L -> OPEN`

## What success means

The first measurement question is not “is Strong Cocktail profitable on one morning?”

It is:

1. Does Strong Cocktail capture a larger fraction of meaningful fast excursions than Cocktail Mode #1?
2. Does it avoid more false flips than the raw 1m MACD control?
3. Does it outperform the 1m control after enough independent market episodes to make the added complexity defensible?
4. Are gains coming from robust event detection rather than one threshold accidentally fitted to NAS100?

Until those questions have data behind them, Strong Cocktail remains a versioned hypothesis.
