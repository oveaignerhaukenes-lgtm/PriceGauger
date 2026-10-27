# MACD+Stoch V2.2 Flip + real 1s impulse research (2026-10-27)

## Scope
- New independent V3 catalog key `macd-stoch-v2-2-flip` / UI
  **MACD+Stoch V2.2 · Flip**, LIVE route selectable on an expressly
  armed account. Not automatically applied to any active account.
- Keep V2.1 composite, two-bar FLAT→OPEN rule, same-direction BUILD
  momentum acceleration and the existing Saxo legal lot/margin/cap checks.
- Only change **strong adverse reversal** on a fully closed signal bar:
  score magnitude >=0.30 when opposite to present inventory directly
  proposes the smallest legal position on the new side. Weak opposite
  composite still proposes FLAT. No new broker netting path is introduced.
  V3 `plan_execution_v3` still requires CLOSE -> CONFIRM_FLAT -> OPEN.
  No bypass of deduplication, pending order, precheck, cost guard, margin,
  exact account owner or existing LIVE protective modifiers. This is not
  a promise to fill opposite orders in the same second; actual order
  reconciliation and costs will limit realized responsiveness.
- Analyse / V2.1 Tempo-lab now also offers **V2.2** alongside V2.1
  flat-first and V2.1 1bar PAPER-net flip at 15s/30s/60s. Subminute
  comparisons are PAPER only. The existing direct BBO fill proxy
  underestimates actual Saxo CLOSE/CONFIRM/OPEN reversal latency and cannot
  establish V2.2 LIVE P/L.

## New read-only second impulse research
- Analyse / Tech100 sekundimpulser loads real `lsim_hyper_quotes_1s`
  bid/ask records for exact Saxo UIC, no interpolation from 1m OHLC.
- Causal event selection: lookback 5/10/20/30 seconds, absolute threshold
  2/4/6/8/10/15/20 basis points; one crossing selected, then 125s
  embargo per parameter pair. Outcomes at 30/60/120 seconds.
- Measures fraction ending net positive after indicative bid/ask,
  half-threshold continuation-before-reversal fraction, maximum favorable
  continuation, time-to-favorable-extreme, fraction retraced from that extreme
  at fixed horizon, observed spread and actual sample coverage.
- Observations split chronologically first 70% / final 30%.
  Training events whose scoring horizon crosses the boundary are excluded,
  with no using future price to create an impulse signal.
- Any missing/wide quote interval splits sessions; thin data produce no
  claimed winner. Only market-price conditional description, no true Saxo
  fills, causal guarantee or prospective profitability evidence.
- The connector cannot directly query the Railway Postgres table through
  its management API, so numerical market results must be computed by the
  read-only application page using its already connected database.
  Never fabricate numerical outcomes from GitHub source or Railway logs.

## Next tests/research
1. Run actual stored Tech100 UIC on 3/6/12/24-hour samples and export
   aggregated table; check minimum 25 event count per held-out threshold.
2. Recheck whether profitable periods survive real Saxo margin/cost and
   V3 two-step reverse latency; PAPER indicated next-BBO entry only.
3. Distinguish impulses that mean-revert from persistent trend: direction,
   time of day, NFP/event shocks vs non-news, underlying 1m volatility,
   confirmed LH/LL/HH/HL structure (see issue #812).
4. Compare V2.2 to V2.1 on identical chronology before selecting any
   active LIVE account. Treat price-triggering model as research only.
