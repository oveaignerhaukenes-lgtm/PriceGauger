# MTF 30/10/5 long/short flip — LIVE v1

This strategy is the symmetric two-sided version of the reviewed MTF long/flat and short/flat policies. It changes strategy intent only; Saxo order authority remains in the existing guarded CLOSE and OPEN executors.

## Signal hierarchy

- LONG early entry: closed 5m MACD `CROSS_UP` while closed 30m context is `BULLISH` or `RECOVERING`.
- SHORT early entry: closed 5m MACD `CROSS_DOWN` while closed 30m context is `BEARISH` or `DETERIORATING`.
- Closed 10m MACD validates the provisional leg or can reject it before 30m confirmation.
- A failed provisional/10m leg exits to FLAT only. Fast-clock noise never carries a reversal target.
- A closed opposite 30m cross is the sole carried flip signal:
  - LONG + 30m `CROSS_DOWN` -> CLOSE LONG -> confirmed FLAT -> OPEN SHORT.
  - SHORT + 30m `CROSS_UP` -> CLOSE SHORT -> confirmed FLAT -> OPEN LONG.

## Execution boundary

The MTF flip runtime never calls Saxo order endpoints. It only persists strategy evaluations and ordinary `OPEN` / `CLOSE` execution requests.

Reversal is always two-step. There is no one-order reverse and no pyramiding. The opposite OPEN is emitted only after Saxo exposure is observed FLAT, then the existing LIVE OPEN gate independently requires:

- active exact strategy enrollment;
- current entry authority and LIVE OPEN arming;
- exact Product Admission for the requested direction;
- explicit NBP / limited-loss acknowledgement as applicable;
- settled PG close/P&L provenance (or the audited one-shot strategy-switch FLAT handoff for the first entry of a new cohort);
- current settled pilot equity and Margin Envelope;
- no current product exposure and no working order;
- final Saxo precheck immediately before durable submit/POST.

## Restart / outage behavior

Each 5m, 10m and 30m closed-bar cursor is persisted. First start adopts actual Saxo exposure and writes `BOOTSTRAP_NO_REPLAY`; historical crosses are not replayed into orders. During an outage only the latest current closed pair is considered and stale pairs advance cursors without order creation.

A carried 30m reversal is persisted as immutable intent so it can survive the CLOSE -> FLAT -> OPEN lifecycle. A newer closed 30m cross can supersede that pending target; 5m/10m bars cannot.

## Activation

The strategy key is `macd-mtf-30-10-5-long-short-v1`. It requires Product Admission for **both LONG and SHORT** before Full auto can be armed. Strategy switching itself sends no order and leaves LIVE OPEN disarmed.
