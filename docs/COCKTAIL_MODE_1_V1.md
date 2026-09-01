# Cocktail Mode #1 — adaptive MTF shadow v1

Cocktail Mode #1 is the first cohesive adaptive strategy engine in PriceGauger. The initial deployment is **SHADOW ONLY**. It has no Saxo POST authority, does not emit execution requests, and does not alter the currently active LIVE AutoManager pilot.

The purpose of v1 is to establish a coherent data and decision basis that can be measured before any LIVE promotion.

## 1. Canonical time principle

The canonical technical event is the **MACD cross time**, not the eventual close of the indicator timeframe candle.

PriceGauger uses fully persisted canonical 1-minute bars as the observation clock. On each newly closed canonical 1m bar it rebuilds the currently forming 5m, 10m, 15m and 30m bars and recalculates MACD 12/26/9 for all four clocks.

For every sign change of `MACD - signal` the engine stores:

- `action_at`: first fully observed canonical 1m close carrying the new sign. This is the deterministic authority for replay/comparison.
- an interpolated cross estimate between the previous and current 1m spread. This is analytics only; it never outranks the observed canonical timestamp.
- spread, normalized spread velocity and acceleration at the observation.

A timeframe therefore describes the **scale of the MACD**, not how long the engine must wait before noticing a cross.

### Data-gap invariant

A MACD cross is never inferred across a gap larger than the configured contiguous-data tolerance (v1: 3 minutes). Missing continuity creates `DATA_GAP_PAUSE`; exposure is modeled FLAT rather than assigning false precision to a cross that may have happened inside the gap.

## 2. Primary objective

Cocktail Mode #1 is not optimized to win every small oscillation. The primary objective is to stay aligned with large directional moves while reducing time spent exposed to ambiguous chop.

`FLAT` is therefore an active strategy state, not an absence of a decision.

Evidence required to **leave an existing exposure for FLAT** is intentionally weaker than evidence required to **open the opposite exposure**.

If a later LIVE adapter is approved, every reversal must still obey the execution invariant:

`LONG -> CLOSE -> confirmed Saxo FLAT -> OPEN SHORT`

or

`SHORT -> CLOSE -> confirmed Saxo FLAT -> OPEN LONG`

Cocktail Mode #1 itself contains no one-order reverse path.

## 3. Strategy modes

### NORMAL

Normal market behavior uses 5m as the early transition sensor and 10m as the normal confirmation clock.

A qualified opposite 5m cross causes the model to go FLAT first. It then waits for 10m confirmation before taking the opposite side. If 5m crosses back before confirmation, the pending transition is cancelled and the model remains FLAT.

Low activity plus 5m/10m disagreement is explicitly treated as insufficient information and produces FLAT/pause.

### SHOCK

SHOCK is the fast path for a move that may represent new information or an abrupt regime change not yet represented by slow indicators.

Initial v1 qualification requires all of:

- 1m range >= 1.50x the rolling median 1m range;
- robust activity z-score >= +2.0;
- 5m net price displacement >= 0.50 ATR(14) on 5m;
- 5m directional efficiency >= 0.70;
- two consecutive 1m closes beyond recent support/resistance plus a 0.10 ATR5 buffer;
- 5m MACD confirms the price direction by a current cross or sufficiently strong same-direction normalized spread velocity.

When the full profile is present, SHOCK may carry an immediate opposite shadow target instead of waiting for 10m/15m/30m. A future LIVE adapter must still translate this into the ordinary safe CLOSE -> FLAT -> OPEN execution sequence.

SHOCK outranks TREND_LOCK: a sufficiently strong break is allowed to say that the old slow trend may no longer be authoritative.

## 4. TREND_LOCK

TREND_LOCK protects a strong established 30m trend from ordinary fast-clock counter-noise.

Initial v1 qualification requires:

- 30m MACD spread has the same sign over the latest three canonical 1m observations;
- absolute 30m spread is expanding on all three observations;
- normalized 30m MACD spread velocity points in the same direction and has magnitude >= 0.015 ATR30 per 1m observation;
- 30m directional price efficiency >= 0.45.

When current exposure is aligned with TREND_LOCK:

- ordinary 1m/5m counter-signals are ignored;
- a 10m counter-cross exits to FLAT and creates a pending opposite direction;
- the opposite exposure requires 15m confirmation;
- a fully qualified SHOCK may override the lock earlier.

The model therefore gives a strong trend inertia, but does not require waiting for a 30m candle close to protect capital.

## 5. WHIPSAW

WHIPSAW is an explicit pause regime intended to prevent repeated MACD flips from consuming the edge of a low-cost but noisy market.

Initial v1 entry condition:

- at least 3 observed 5m/10m cross events within 30 minutes;
- and either 30m directional efficiency < 0.25 or net 30m displacement < 0.40 ATR10.

WHIPSAW forces FLAT and remains FLAT until a qualified escape occurs.

Initial v1 escape paths are:

- a qualified SHOCK;
- an observed forming-30m MACD cross on the canonical 1m clock;
- or a support/resistance breakout with 10m and 15m aligned, >=0.50 ATR5 displacement and >=0.15 ATR5 break distance.

The thresholds are deliberately explicit so they can be measured and revised rather than silently tuned by intuition.

## 6. Activity and volume

Index-CFD volume is not assumed to be equivalent to a centralized futures-volume feed.

Cocktail Mode #1 therefore treats activity as a feature with provenance:

- when canonical volume is sufficiently populated, robust volume activity may contribute;
- otherwise 1m true/range expansion acts as the primary activity proxy;
- each persisted sample records the activity source.

A future version may add NQ futures or another higher-quality volume reference, but v1 must not manufacture missing volume.

## 7. Support/resistance v1

Support/resistance is intentionally mechanical in v1 so the result is replayable.

The engine uses the prior 60 canonical 1m bars while excluding the latest 5 minutes from the reference window. The lowest low and highest high are the initial support/resistance boundaries. A break must persist for two consecutive 1m closes beyond the configured ATR buffer.

This is a calibration baseline, not a claim that simple rolling extrema are the final support/resistance model.

## 8. Persisted research features

Every canonical 1m sample persists enough context to answer *why* the strategy held, flattened, opened or flipped:

- position before/after;
- mode before/after;
- decision action and reason;
- pending direction and confirmation timeframe;
- observed 5/10/15/30m cross events and interpolated cross estimates;
- MACD spreads and normalized spread velocities;
- activity z-score and source;
- 1m range ratio;
- 5m/30m directional efficiency;
- normalized price displacement;
- support/resistance and break distance;
- SHOCK, TREND_LOCK, WHIPSAW and escape state;
- data-gap state;
- gross shadow return and transition count;
- immutable configuration version and source kind.

This is the calibration dataset for later threshold analysis.

## 9. P/L semantics

Cocktail Mode #1 starts with `BOOTSTRAP_NO_REPLAY` and FLAT exposure at its first live data-collection point. Historical crosses are not replayed into a fictitious pre-deployment position.

Its P/L line therefore begins only when the shadow engine actually starts collecting data. It is displayed beside the existing canonical controls on the same linked product timeline.

V1 shadow performance is **gross**: spread, slippage, financing and margin are not yet deducted. Transition count is recorded so a later cost model can penalize frequent switching. Direct shadow flips close and reopen at the same sampled price for research accounting; this does not imply a future LIVE one-order reversal.

No profitability inference should be made from a short sample or a single market regime.

## 10. Deliberately excluded authority

V1 does not use RSI or Stochastic as decision authority. They may be logged as research features later if we want to test whether they add information beyond the multi-timeframe MACD/regime model.

V1 also has no LLM decision authority, no sizing authority, no Product Admission authority and no Saxo order path.

## 11. Initial threshold table

| Feature | v1 threshold |
| --- | ---: |
| Contiguous 1m gap tolerance | 3 min |
| Low-activity range ratio | < 0.75x median 1m range |
| Ambiguous 10m MACD spread | < 0.03 ATR10 |
| SHOCK 1m range | >= 1.50x median |
| SHOCK activity z | >= +2.0 |
| SHOCK 5m displacement | >= 0.50 ATR5 |
| SHOCK 5m efficiency | >= 0.70 |
| SHOCK S/R buffer | >= 0.10 ATR5 |
| SHOCK MACD velocity | >= 0.03 ATR5 |
| TREND_LOCK 30m MACD velocity | >= 0.015 ATR30 |
| TREND_LOCK 30m efficiency | >= 0.45 |
| WHIPSAW fast crosses | >= 3 / 30m |
| WHIPSAW efficiency | < 0.25 |
| WHIPSAW displacement | < 0.40 ATR10 |
| WHIPSAW escape displacement | >= 0.50 ATR5 |
| WHIPSAW escape S/R buffer | >= 0.15 ATR5 |

These values are versioned hypotheses. Any later threshold change must create an auditable configuration version so historical performance is not silently reinterpreted.
