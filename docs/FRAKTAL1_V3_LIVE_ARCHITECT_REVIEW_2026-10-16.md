# Fraktal#1 · SIM/PAPER-only, 2026-10-18

**This is a research rollout, not a LIVE-capable trading strategy.**
The old #729 LIVE-capable PR remains unmerged and is superseded by an
isolated main-based SIM-only integration. No changes to the LIVE worker,
account configuration, trader arming, Saxo broker adapter or orders.

Production-safe double LIVE guard:
- `live_config_issues_v3` rejects catalog strategy `fraktal-1` for all timeframes.
- `STRATEGIES_V3['fraktal-1-v1'].live_route_enabled=False` makes LIVE worker
  reject any bypassed config before broker orders.

SIM: `fraktal-1` uses canonical completed 1m price bars and three confirmed
swing thresholds 0.05/0.15/0.35%, at most one configured Saxo legal unit
for new entries. Opposite confirmed swing produces target FLAT before reversal;
no same-bar flip. Causal close check requires +10 seconds. Missing provider
bar / duplicate, initial activation and context switch do not replay old entries.

The candidate is **not** proven profitable by regression tests. Before any
future small-account LIVE pilot, demonstrate same-clock OOS performance,
spread+fees/funding, time to confirm actual broker fills, oversize inventory
handling (current `HOLD_OVERSIZED` needs risk review), restart/gaps, and
verified CLOSE→FLAT under timeout/partial-fills. User must explicitly approve
any changes to account arming and lifting LIVE guard.

Original research and historical contract retained in #729.
