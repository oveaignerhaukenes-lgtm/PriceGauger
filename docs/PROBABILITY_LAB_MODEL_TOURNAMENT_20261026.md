# Probability Lab: multi-process stochastic research (2026-10-26)

## Scope

Extension to the read-only 1m Probability Lab only. All estimates are based
on exact stored subscribed Saxo 1m OHLC closes; no broker execution,
account access, order state, arming, extra market subscription, secrets,
database schema or background jobs. Existing models and report remain.

On clicking the historical test button the lab now also runs nine fixed,
pre-specified models on the same 1m close-to-close forward target:

1. Rolling categorical frequency (3-class proper scoring baseline)
2. Sign-state Markov (two prior minute directions; shrinkage)
3. Poisson/Skellam from count of green/red **minute** changes (not true tick events)
4. Exponentially decayed categorical/Dirichlet frequencies
5. Streak-length-conditioned Markov (truncated run length)
6. Volatility-regime-conditioned empirical frequency (causal 20m realized volatility)
7. Geometric Brownian/normal log-return diffusion
8. Discrete Ornstein–Uhlenbeck/AR(1) **on log returns**, not price levels
9. Jump-diffusion-inspired normal-mixture sign model

The latter two are discrete, approximate forecasting models, not fitted
physical continuous-time diffusion paths or event-time Hawkes calibration.
The current minute data cannot identify exact tick event intensities.
No claim of a true HMM, GARCH or Hawkes fit is made.

## Validation design

- One documented forward horizon (1/2/5/10 minute close-to-close).
- Every feature at time t and every training return label j->j+h is resolved
  by t; no future/high-low ordering assumptions.
- Each disconnected 1m segment is separately warmed up, never bridged.
- Fixed model roster and settings, no automatic in-sample optimizer.
- Score only on UTC-aligned **nonoverlapping horizon blocks**.
- Select the best Brier model on first ~70%; evaluate selected model on
  final ~30% holdout after a purge around the split.
- Report validation and holdout Brier (lower better), log-loss,
  three-class hit rate, hypothetically signaled close-to-close net returns
  after **user-provided** roundtrip cost, and a reproducible approximate
  moving-block bootstrap interval for **paired Brier improvement vs baseline**.
- Candidate only obtains evidence flag if validation and holdout improvement
  are positive, heldout score sample >=100, and lower bootstrap gain bound >0.
  A positive result means **probability forecast improvement**, not proof
  that a position can be traded profitably at the assumed close.
- Extra cost guard for recommendation: observed positive hypothetical mean
  return and >=30 heldout signals. This only qualifies for **prospective PAPER**,
  never LIVE. No backtest equity curve or actual Saxo fill is implied.
- Show a deterministic, data-dependent Norwegian summary, interpretation,
  uncertainty/limitations and conservative recommendation. Export manifest
  of all model scores/selected-model explanation alongside existing 1m
  forecast JSON.

## Operational testing

1. GitHub CI must compile and pass all Probability Lab/tests.
2. Review PR then merge; Railway web must serve new main SHA with healthy logs.
3. User opens Analyse -> Probability Lab and runs real Tech100 UIC 4912 on
   a sizable period with contiguous 1m observations.
4. Check enough distinct days/regimes, gap counts and holdout sample sizes.
   Re-run different windows/horizons for **diagnostic robustness**, but never
   promote a model by repeatedly selecting the best result on the same
   heldout period. For a final model, reserve a newer untouched period.
5. A predictive winner is NOT equivalent to net trade profitability.
   Actual executable fill costs, order latency, drawdown and account reconciliation
   require a separate prospective research protocol and user approval.

## Limitations

- This code can't itself access the user's production SQL through GitHub/Railway
  management connectors. Real historical return outcomes are calculated only
  when the lab runs in the user's connected PriceGauger application.
- Existing 1m close-to-close labeling differs from *next candle color* based
  on open-to-close, particularly around gaps.
- Bootstrap interval is approximate, conditional on single-sample candidate
  selection and possible nonstationarity; not a guarantee against data mining.
- Historical close-to-close percentage after assumed roundtrip bps is merely
  an upper-bound-style directional diagnostic, not attainable Saxo P/L.
