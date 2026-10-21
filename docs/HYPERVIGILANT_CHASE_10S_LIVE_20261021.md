# HyperVigilant Chase 10s: V3 strategy options

FAST and FILTERED reuse the already-tested prospective bid/ask impulse detector. They read actual Saxo Tech100 quotes captured up to one per second. New signal decisions require fresh, continuous observations over ten seconds and a bounded spread.

Both strategies can request the opposite position immediately on a reversal signal. The existing V3 process first closes the old position, confirms the account is flat, and then opens the other side only if a new valid signal remains. This is not an atomic one-order reversal or a guarantee of ten-second execution.

Both variants appear in the normal V3 selector. Choosing a strategy does not automatically turn on LIVE or change an account. Usual exact-account authority, margin limits, cost checks and durable order reconciliation remain in force.

Historical 1m V3 SIM is deliberately not used for ten-second strategies; see the separate HyperChase prospective PAPER panel. Review actual quote density, latency and observed cost-adjusted outcomes before any larger allocation.

See PROJECT_STATE.md for session continuity and next validation steps.
