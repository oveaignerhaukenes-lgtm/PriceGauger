# V3 LIVE inventory ownership — 2026-10-02

## Contract

When V3 is LIVE, its assigned Saxo account + UIC + asset type is the ownership boundary.

- Saxo exact inventory is the source of truth.
- A manual position on that exact boundary is adopted by V3; it is not foreign inventory.
- A stale pending expectation is retired when exact inventory conflicts with it, so the next cycle can manage the observed position.
- Management authority covers the whole observed position, including an oversized manual position.
- Expansion authority remains separate: OPEN/ADD must still pass the configured V3 execution/exposure policy and Saxo precheck.
- REDUCE/CLOSE may shrink an adopted oversized position toward the strategy/risk-approved target even when the current inventory is larger than the normal allocation.
- Other accounts/instruments are never adopted by this trader.

This supports intentional temporary manual oversizing for an expected move: V3 can subsequently reduce the position as its target falls, without granting itself permission to expand beyond its configured authority.