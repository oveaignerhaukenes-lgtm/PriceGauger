# Aen#1 — costed price-breakout shadow

Hypothesis: capture directional NAS100 runs that survive spread, while remaining
flat during unproductive back-and-forth. This is an independently specified
candidate, not evidence of profitability or an AI-directed trading account.

The policy consumes **completed, contiguous 1m closes** from the same canonical
instrument as the existing strategy comparisons. It estimates 60m directional
efficiency from price, then requires a 12m high/low breakout and a 3m impulse
above a cost/noise hurdle. A convincing 60m direction prevents countertrend
entry. A reversal of the 60m regime or a trailing price retracement sends FLAT;
there is no direct reversal. A five-minute cooldown follows every exit. Missing
minutes clear the warmup and request FLAT.

The Strategy Lab series is charged an assumed **two index points spread**:
half per entry or exit and a full spread for a direct reversal. The curve is
1x before the existing pilot-leverage transform. This cost is a fixed research
assumption; it is not an observed Saxo fill or slippage. Signals execute on
the sampled close in this shadow simulation; realistic delayed fills can be
materially worse. Market closure gaps and missing bars need specific live
execution rules before promotion.

The model has no live enrollment or Saxo order authority. Assess its net
performance, number of switches, drawdown and missing-bar behavior over several
different sessions and against existing MACD-A/SFL/Hunter candidates before
considering a 0.01 pilot. Do not tune thresholds to a single trading day.
