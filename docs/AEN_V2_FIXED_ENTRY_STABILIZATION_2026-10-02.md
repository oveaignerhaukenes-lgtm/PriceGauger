# V2 fixed-entry stabilization — 2026-10-02

Goal: prove the V2 OPEN chain with a small configured amount before changing sizing behavior further.

Runtime contract:
- `PRICEGAUGER_V2_ENTRY_AMOUNT` optionally overrides V2 sizing for LIVE OPEN.
- The value is deployment configuration, not an instrument hard-code.
- If unset, the existing DB-backed sizing policy remains authoritative.
- The configured value is normalized against Saxo instrument amount precision and minimum size.
- Saxo order precheck, Margin Envelope, current strategy authority, FLAT check, duplicate working-order prevention, durable submit state and reconciliation remain in force.
- A rejected configured amount now reports the exact Saxo precheck/disclaimer/Margin Envelope reason instead of collapsing immediately into the generic maximum-sizing error.

Initial production test value: `0.01`. This is only a test configuration and can later be changed without code changes.
