# V5 quantized online loss feedback — first PAPER screen

Research only. No Saxo orders, account arming, deployed strategy, or verified live fills.

## Hypothesis fixed before holdout

After a *completed* simulated losing round-trip, make the next OPEN/ADD progressively harder by quantizing two market measures from already completed bars:

- Last twelve 1m steps' **directional efficiency** (`abs(net change) / sum(abs(step changes))`).
- Last six minutes' **side-aligned momentum**, divided by the previous fourteen 1m true ranges' mean.

The active thresholds depend only on 0, 1 or 2+ net losing trades in a rolling window of three paper trades (costed at 4bp roundtrip spread); memory expires after 35 minutes without a fresh loss. Four rules were selected *before* reading Friday's data: fixed (constant base thresholds, control), minimal, adaptive and cautious. V3 is always authoritative on exits; V5 never turns a V3 FLAT into HOLD.

## Training: 16–19 November 2026, frozen comparisons

Source: actual Saxo UIC 4912 exported one-minute OHLC, four independent days. Each day and side starts with a separate hypothetical 10,000 NOK NAV, 0.03 max lots, 10 NOK/point, S1/R5/E2, next-bar OPEN execution, 4bp user-cost scenario and no commission. These are *sums of individual percentage-point returns*, **not** compounded portfolio returns or real account results.

| Model | Four LONG days (pp sum) | Four SHORT days (pp sum) | Eight day×side cases (pp sum) |
|---|---:|---:|---:|
| Unchanged V3 | −3.25535 | −1.66215 | −4.91750 |
| V5 fixed-entry control | −2.90631 | −1.57244 | −4.47875 |
| V5 minimal loss-adaptive | −3.25550 | −1.59900 | −4.85450 |
| **V5 adaptive** | **−2.71148** | **−1.47181** | **−4.18329** |
| V5 cautious loss-adaptive | −2.69792 | −1.62202 | −4.31994 |

**Decision made before 20 November was opened:** Freeze **V5 adaptive** as the sole adaptive candidate for a one-day chronological holdout, with unchanged V3 and V5 fixed control as nonselected comparators. The adaptive rule improved eight-case training by +0.73421pp against V3 and +0.29546pp against fixed-gate control, but all tested aggregate returns remained negative.

## Interpretation and limitations

- This small, predominantly falling sample cannot establish statistical significance or robustness in sideways and rising markets. We have just four independent training days, two coupled opposite-side signals per day, and one reserved holdout day. Sequentially trying more variants on the reserved day would leak its information into selection.
- Reduced losses may reflect fewer openings/spread charges rather than adaptation after losses. The fixed-gate ablation explicitly separates this from online loss feedback; the observed extra training improvement is modest and must replicate.
- Simulated positions use an assumed whole-position next-open fill; real Saxo fill, slip, broker-authoritative position reconciliation, partial fills, restarts and persistent learning state are not verified. This is a research scaffold, **not a LIVE-ready V5**.
- Future work: at least several weeks of non-overlapping bull/bear/sideways days, spread and delay stress, chronological walk-forward with untouched periods, risk/drawdown comparison, and no modification to production order paths until all protective gates are formally reviewed.

## Holdout

20 November 2026 was held aside until **adaptive** was frozen. The exact previously selected V3/fixed/adaptive trio was run on Friday with identical 4bp execution costs. No hyperparameters were changed after viewing Friday.

| Model | Fri LONG % | Fri SHORT % | Sum, two independent cases (pp) |
|---|---:|---:|---:|
| Unchanged V3 | −1.689405 | −0.831974 | −2.521379 |
| V5 fixed-entry control | −1.558654 | −0.654091 | −2.212745 |
| **V5 adaptive (frozen winner)** | **−1.485066** | **−0.673837** | **−2.158903** |

In this one-day holdout, adaptive improved +0.362476pp across two paper cases versus V3, but only **+0.053842pp** versus the non-adaptive fixed-entry control. The SHORT adaptive result was slightly worse than fixed (−0.019746pp); both remained negative. This is *preliminary replication*, not a statistically significant edge, and should not be extrapolated to LIVE return.

### Robustness check

An additional **8bp** spread stress on the same frozen trio (not used to retune or re-rank candidates) was run separately:

| Model | Fri LONG % (8bp) | Fri SHORT % (8bp) | Sum (pp) |
|---|---:|---:|---:|
| Unchanged V3 | −2.021879 | −1.173037 | −3.194916 |
| V5 fixed-entry control | −1.870768 | −0.985132 | −2.855900 |
| **V5 adaptive (same frozen policy)** | **−1.776452** | **−1.004874** | **−2.781326** |

Thus adaptive improved +0.413590pp vs V3 and +0.074574pp vs fixed on this same day under doubled assumed spread, but *both legs still lost money*. The repeat-day 8bp check is a **sensitivity test**, not an independent second out-of-sample observation. No further model ranking against the 20 November dataset is legitimate.
