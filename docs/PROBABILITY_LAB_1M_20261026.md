# Probability Lab 1m (2026-10-26) — research only

## Source reality
- Saxo chart refresh around 1s shows the **currently forming 1m candle**, not an
  archived second-by-second historical price series.
- Canonical persisted market bars are completed **1m OHLC** in
  pg_v2_market_bars_1m, keyed by **exact subscribed instrument_id**.
- No tick history, archived per-second BBO or genuine Hawkes event times are
  available for retrospective experiments from that table.
- Prospective quote/HyperChase PAPER data is independent and must not be
  silently substituted for historical tick input.

## Isolated UI
Analyse → Probability Lab. Uses GET-only local DB read through
CanonicalMarketBarStoreV2.load_instrument_range(instrument_id=...).
No broker trading, account/strategy authority, state writes, env vars,
order creation, live worker hooks or required database migration.

## Models
1. **Unconditional rolling baseline**: past, fully resolved h-minute
   close-to-close UP/DOWN/FLAT frequencies with Laplace smoothing.
2. **Markov(1–3)**: conditional distribution of subsequent h-minute return
   given last 1–3 one-minute close-to-close signs. Shrink toward contemporaneous
   rolling baseline (12 prior observations) to mitigate tiny matching samples.
3. **Poisson/Skellam proxy**: observed number of positive/negative one-minute
   price-change signs per minute provides Poisson rates; difference of
   independent Poisson counts implies UP/DOWN/TIE mass over 1/2/5/10 minutes.
   This is a deliberately **falsifiable proxy** and is not a calibrated
   point-process derived from actual individual ticks.

**Target**: P(close(t+h) > close(t)), P(<), P(=) for h in (1,2,5,10)
completed one-minute bars. Not next candle's OPEN-to-CLOSE color; those
questions differ if opening gaps are present.

**Training**: strictly chronological as-of evaluation; only use a
training outcome at j when j+h <= current as-of index i.
Gaps in 1m chronology split independent runs. No cross-gap forecasts,
as-of indicators, labels or implied price fills. Short segments skipped.

## Evaluation
- Three-class Brier score, categorical log-loss, three-class hit rate.
- Calibration bins for P(UP) with observed UP frequency and sample count.
- Optional threshold for hypothetically acting on direction.
- Hypothetical close-to-close return per separately scored forecast minus
  a **user-provided** roundtrip basis-point scenario, not actual or modeled
  Saxo fill/spread from historical BBO. Overlapping horizons are **not**
  composable into equity or cumulative P/L.
- Export timestamped model probabilities, actual outcomes, as-of,
  settings and assumptions in JSON for further analysis.

## Validation/release boundaries
- Tests: probability normalization, tail/symmetry, horizon labels,
  prefix invariance, changing future target cannot change forecast,
  chronology-gap isolation, input validation, and cost diagnostics.
- Need CI, review and real Tech100 UIC-4912 canonical DB example.
  Sample in-sample or synthetic results are *not* profitability proof.
- Do not automatically enable any V3 LIVE instance on merge or deploy.
- Draft Probability Desk PR #804 concerns 1D/5D price/macro forecasting.
  This 1m Probability Lab is separate and should not silently overwrite it.

## Follow-up data architecture (not implemented)
If tick-event Hawkes is to be evaluated, introduce a bounded per-UID
read-only time-stamped bid/ask sample storage with freshness, gaps,
deduplication, volume budget, retention and exact source provenance.
Do not repurpose ephemeral chart forming candles into historic ticks.
