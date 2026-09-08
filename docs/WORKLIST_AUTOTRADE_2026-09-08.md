# AutoTrade stabilization worklist — 2026-09-08

## Done before this worklist

- [x] Simple LIVE MACD 1m/2m/5m/15m uses the forming intrabar clock.
- [x] Simple LIVE MACD is level-triggered: positive spread => LONG, negative spread => SHORT.
- [x] Simple LIVE MACD benchmark forces MAX_WITHIN_PILOT for LONG and SHORT.
- [x] Reversal execution remains CLOSE -> broker-confirmed FLAT -> OPEN opposite.
- [x] Simple MACD CLOSE requests may rebase to the latest exact net basis when only amount/open basis changed and product/side identity remains compatible.

## Current implementation pass

- [x] Separate `Manage position` authority from `AutoTrade` strategy authority.
- [x] Turning Manage position OFF also turns AutoTrade OFF and retires unstarted strategy requests.
- [x] AutoTrade cannot be enabled while Manage position is OFF.
- [x] Manual BUY/SELL targets remain available independently of AutoTrade.
- [ ] Make event/activity wording state-based (`LONG target -> close SHORT`) rather than legacy cross-label wording.
- [ ] Harmonize classic simple 30m MACD with the same intrabar/state-driven binary benchmark contract.
- [ ] Decide whether 10m/20m should remain shadow/comparison or be promoted to simple LIVE binary controls.
- [ ] Add experimental `5m MACD + Price Structure + Impulse` strategy as a separate strategy key; do not contaminate the pure-MACD benchmark.
- [ ] Remove remaining TradingDesk debug chrome (`unknown · unknown`, redundant signal aggregate/status remnants) after execution mechanics are stable.

## Live acceptance test

For every simple LIVE MACD controller under test:

1. record current MACD side and current Saxo net side;
2. on each compatible sign change, verify desired target flips immediately;
3. verify full current net exposure is closed;
4. verify broker FLAT is observed before opposite OPEN;
5. verify new OPEN uses MAX_WITHIN_PILOT subject to Saxo precheck/Margin Envelope;
6. if any step is blocked, preserve the current target and reconcile on the next cycle rather than waiting for a new cross;
7. no intentional simultaneous long/short exposure and no strategic FLAT/wait/confirmation rule in the pure benchmark.
