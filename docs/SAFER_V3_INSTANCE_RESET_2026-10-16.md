# V3 controlled per-instance reset / recovery (2026-10-16)

**Problem:** A V3 trader can become stuck behind a durable unresolved order
when Saxo returned an error, a request timed out, or fill reconciliation
could not finish. A simple OFF/ON does not delete durable order state.

**Critical existing flaw fixed:** \`pages/0_AutoTrader_V3.py\` formerly
exposed "Frigi gammel pending-lock og slå LIVE av", which **unconditionally**
set any pending request to REJECTED (including SUBMITTING, SUBMITTED,
UNKNOWN) without proving that Saxo had not received an order. That could
allow duplicates on a subsequent arm. This shortcut was removed.

**Operator experience:** Under "Administrer instansen" for **every V3
instance** (Fleet and any shared canonical controls), use
"Kontroller / reset fastlåst instans". It invokes a single shared
\`reset_instance_safely_v3(instance_id=...)\` backend; no cross-account
mutation. This is a reset of a **verified pre-submit reservation only**,
not a cancellation of broker orders.

**What reset does**
1. Loads exact active V3 instance and durable pending order scoped to its
   Saxo account + product. No PIN is logged or needed in this workflow.
2. If stale \`RESERVED\` without broker ID, delegates to existing
   \`recover_stale_reserved_v3\`: pre-order Saxo inventory unchanged,
   all account working orders known/absent, fresh second inventory read,
   and atomic compare-and-swap RESERVED→REJECTED guarded by timestamp.
   Worker cannot later claim the old request and POST it.
3. If \`SUBMITTING\`, \`SUBMITTED\`, \`UNKNOWN\` or any broker-ID:
   **denies reset**, keeps lock and original audit. Requires manual
   Saxo confirmation / independent recovery design before retry.
4. With no durable pending: independently checks account identity, broker
   signed inventory twice, working orders and pending again; reports
   \`ALREADY_CLEAR\`, with no DB/config/authority writes.
5. Never deletes a Saxo order, flattens an existing position, replays a
   historical strategy signal, modifies risk memory, or toggles LIVE/SIM.
   A still-armed instance continues under its **existing** configuration
   on the worker's next eligible signal; an OFF instance remains OFF.

**Limits:** The operator control is not a blanket "clear everything"
button; SUBMITTED and UNKNOWN cannot be cleared blindly because they may
have filled. No broker DELETE/POST routes are added. Market outages and
persistent reconciliation bugs may still require separate diagnosis.

**Testing:** new pure/test-double tests + existing stale RESERVED
CAS/fill/working-order protections. No automatic execution during deploy.
