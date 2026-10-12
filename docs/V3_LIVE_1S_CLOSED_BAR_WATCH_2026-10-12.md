# V3 LIVE: 1-second market-data watch, bounded Saxo reconciliation (12 Oct 2026)

## What changed

- V3 LIVE's market-data **watch** now inspects the last ten minutes of canonical, closed Saxo 1m bars roughly every **1 second**.
- An advance in any exact instrument's latest *closed* 1m bar wakes the existing production V3 LIVE evaluation immediately. There is no 30-second idle delay after a fresh bar has arrived.
- An independent **30-second** full evaluation/reconciliation heartbeat still runs when no new bar arrives, notably for manual position changes, pending Saxo orders, new config/arm changes, and reconnect recovery.
- The V3 LIVE order pipeline, durability/idempotency, Saxo account isolation, precheck, size caps, and fail-closed pending-order handling are unchanged.

## Why not make every tick a broker REST evaluation?

The streaming provider already uses a nominal 1000 ms price refresh; but existing LIVE strategies are closed-1m/2m/5m etc strategies, **not intrabar momentum strategies**. Each full V3 cycle currently calls Saxo REST for account data, net positions and product rules/cost checks, for each active trader. Four full broker cycles per second would be costly and could exceed provider quotas. This new watcher only issues one bounded, read-only canonical DB query per second and calls the Saxo cycle **when an actual closed bar advances** or at a slower reconciliation heartbeat.

**Neither 1-second broker execution nor an intrabar signal is promised.** End-to-end reaction time is data-feed latency plus up-to-one-second watcher delay plus whatever the existing broker processing/placement requires. If a full cycle is already processing, the next check happens after that cycle. The V3 closed-bar idempotency still prevents duplicate decisions/requests on the same bar.

Manual flattening while LIVE is armed remains an **explicit request to change broker inventory, not a change to strategy direction**: when target is still LONG, auto-reopening may be correct strategy behavior. The 30-second reconciliation heartbeat handles this without polling Saxo position endpoints at 1 Hz. Market open/close and existing pending-order safeguards remain important; a pending accepted order must never be re-sent just because time elapsed.

## Operational verification

Check worker startup for `v3 LIVE closed-bar watch started poll=1s reconciliation=30s`. New canonical closes yield `v3 LIVE canonical closed-bar advanced; evaluating now`. For inactive markets, expect periodic full checks, not per-second broker traffic. Review provider quota/timeouts and canonical feed freshness in production during regular trading hours. No LIVE account strategy changes, cancels or explicit trade placements accompany this change.
