# PriceGauger Market Rhythm Profile (research-only)

Date: 2026-10-16. This adds **no** LIVE authority, Saxo requests, trading strategy changes,
worker loops, DB schemas or extra quote ingestion. Reuses canonical 1m PRICE already
loaded by Strategy Scoreboard.

## Hypothesis

"CHOPPY" is not one tradeable market state. A stochastic 1m zigzag, a stable
4m oscillation, and a 20m amplitude-shifting cycle require different sampling
and reaction delays. Diagnostic rhythm dimensions:

- **Amplitude:** percent move on the underlying, measured between successive
  threshold-confirmed extrema; distinct from leveraged investor returns.
- **Half-cycle:** peak-to-trough or trough-to-peak duration (minutes).
- **Full-cycle:** peak-to-peak or trough-to-trough duration (minutes).
- **Regularity:** coefficient of variation of observed full-cycle periods.
- **Frequency:** confirmed turns / hour of *observed 1m price bars*.
- **Duration distribution:** completed 1m, 2m, 3–4m, 5–8m and >8m legs.
- **Directional efficiency:** remains in the existing Strategy Scoreboard.

The read-only TradingDesk Strategy Scoreboard panel `Rytmeprofil` shows
6h/24h/7d windows and minimum reversal thresholds **0.05 / 0.10 / 0.25 /
0.50 / 1.00 / 3.00 percent**. For example, a 2m leg with a 0.5% amplitude
can occur inside a 4m full cycle. A 1m reversal of 1% and a 4m cycle of 3%
are distinguishable in the table. These are underlying-percent definitions;
for a particular instrument/leveraged account, use the proper exposure
schedule to translate to expected equity impact.

## Causality

A pivot at 12:00 that is not verified by a >=threshold counter-move until
12:03 has `pivot_at=12:00` and `confirmed_at=12:03`. LIVE/PAPER policy must
never act at 12:00 on this hindsight. The visible summary is explicitly
retrospective, NOT a historical sequence of instantly-available pivot signals.

Only positive canonical 1m CLOSE values count. Incomplete 1m gaps split the
time series so no fake one-minute reversals join separate market sessions.
No intrabar swings shorter than 1m can be detected by these samples; a
separate quote-based validation would be needed for sub-minute dynamics.

A missing sample or low cycle count is shown as unknown, never "perfectly
stable" or zero-period. A 7d window includes any data the canonical feed
actually retained; threshold selection alone proves no net trading edge.

## Next research phase (not implemented by this PR)

1. Freeze strategy versions, timeframes and modifiers into immutable LIVE
   activation epochs and match broker-verified fills / real net P/L to each.
2. Join executions and decision timestamps to **as-of** rhythm profiles
   (trailing windows only) so there is no hindsight cherry-picking.
3. Measure delay from *confirmation* to order, realized capture fraction,
   spread/fees/slippage/funding, and position exposure over cycles.
4. Compare actual V3 decision stream vs V2 Flip, MACD Hold, Histogram and
   AEn variants under **matched costs and same observation windows**, with
   forward out-of-sample tests. Include stratification by period CV and
   directional drift, not merely "CHOPPY".
5. If successful, first offer a READ-ONLY recommendation; switching real
   strategy or timeframe requires separate permission and broker safety.

The analysis panel never changes or arms live strategies.
