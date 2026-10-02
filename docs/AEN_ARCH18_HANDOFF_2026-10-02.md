# AEN Architect 18 handoff — 2026-10-02

## Start here
Continue on branch `aen/v3-adopt-manual-inventory`. Do not reconstruct this from chat. Inspect the branch diff against `main` first because the previous tool session was interrupted mid-work.

Current `main` at start of this work was `f5d8db3323150a97f6253bb4a63cb7b8aaf9d7f4` (PR #616 merged). PR #616 added diagnostic-only V3 pending classification: stale WAIT/conflict => AMBIGUOUS, exact inventory confirmation => RECONCILED; it never authorizes retry.

## Product decision made with Ove
For a V3 engine that is LIVE on an assigned Saxo account + instrument:

1. Saxo observed inventory is truth.
2. LIVE account+instrument gives V3 management authority over the whole observed inventory, including inventory entered manually.
3. A manual position must therefore be adopted automatically; it must not remain permanently BLOCKED as foreign inventory.
4. The configured budget/exposure is **expansion authority**, not management authority.
5. If observed inventory is larger than the configured allocation, V3 may manage/reduce the entire position but must be **reduce-only** until it is back inside the assigned budget.
6. Example: allowed allocation corresponds to 0.03 but user manually enters +0.12. V3 adopts +0.12 and may do 0.12 -> 0.08 -> 0.03 -> 0, or reduce/cross zero as the strategy requires, but may not increase 0.12 -> 0.13 while outside budget.
7. This is intentional so Ove can manually put on a larger position for an expected large move, then let V3 reduce/manage it when the move is over.
8. Scope is strictly the assigned account + UIC + asset type. Never adopt inventory from another account/instrument. Preserve V2/V3 hard separation.

Canonical principle:
`observed inventory = truth`
`LIVE account+instrument = management authority`
`budget = maximum expansion authority, not maximum management authority`

## Existing runtime behavior that must change
`autotrader_v3_live_runtime_v1.py` currently reconciles a durable pending order before evaluating a new target. On CONFLICT it calls `manual_fill_explains_inventory_change_v1`; only a proven manual fill retires the old expectation. Otherwise it records BLOCKED `pending=conflict; unexplained inventory change` and continues forever.

Production evidence before this handoff:
- V3 pilot: `b6008676-ec57-50e9-9cbf-3b0577c643ab`
- expected old pending inventory: `-0.01`
- actual was initially 0, WAIT for ~25m with no retry
- Ove then manually entered LONG +0.12
- runtime saw actual=+0.12 vs expected=-0.01 and correctly failed closed under the old rule
- new product rule supersedes that ownership behavior: because this is V3's LIVE account+instrument, +0.12 should be adopted and managed.

Do **not** simply add retries. Old pending must be retired/adopted deterministically before a new mutation can be sent.

## Important sizing gap discovered
`autotrader_v3_live_sizing_v1.py` currently documents that `policy.max_notional_nok` is diagnostic only. `cap_open_add_amount_v3()` floors to Saxo lot step but deliberately does NOT compare gross CFD notional with cash allocation. Therefore the new reduce-only rule needs a reliable concept of allowed expansion amount/budget. Do not pretend `price * CFD amount <= budget_nok` is necessarily correct cash/margin semantics.

Use broker-native margin/cash impact if available, or otherwise preserve conservative semantics and make the authority decision explicit/testable. The user requirement is semantic: a position above its assigned budget can always be reduced but cannot be expanded further until inside allocation.

## Branch state / warning
Branch `aen/v3-adopt-manual-inventory` was created from main. The interrupted session performed multiple GitHub writes while experimenting. Before doing anything else:

- compare branch to main;
- inspect every changed/new file;
- remove accidental/scratch files if any;
- do not assume the branch is CI-ready;
- do not merge until tests and diff are understood.

Known intentional direction in branch: tests/changes around manual inventory adoption and reduce-only budget authority. Because the session was interrupted, treat all unmerged branch changes as untrusted until reviewed.

## Recommended implementation sequence
1. Audit branch diff vs main and clean scratch changes.
2. Extract a pure authority function for inventory management, with tests. Inputs should include actual signed inventory, proposed target/mutation, and configured expansion limit. Outputs should clearly distinguish NORMAL vs REDUCE_ONLY and permitted mutation.
3. Pending reconciliation: when V3 is LIVE and exact Saxo inventory for its assigned account+instrument differs from stale pending expectation due to a manual/external adjustment, retire the stale pending expectation as adopted inventory rather than permanently blocking. Preserve UNKNOWN broker-order ambiguity where adopting could duplicate an unverified V3 POST.
4. Feed the adopted exact inventory into the normal strategy pipeline on the next cycle.
5. Apply budget authority before POST: reductions/close of oversized inventory remain legal; expansion of absolute exposure while oversized is forbidden; once within budget, normal expansion rules resume.
6. Cover LONG and SHORT symmetrically, including reversal/cross-zero behavior. A reversal must reduce old-side excess before opening new-side exposure beyond zero.
7. Tests must prove: manual +0.12 adopted; oversized position can reduce; cannot increase abs exposure while oversized; can reduce to allocation; normal expansion resumes inside allocation; same rules for negative inventory; other account/instrument is untouched; stale pending is retired without duplicate retry.
8. Open PR, wait for CI, fix failures, merge only green.
9. Wait for Railway production deploy. Inspect `PriceGauger-worker` logs for the pilot above. Verify the stale pending becomes adopted/reconciled and V3 evaluates/manages actual inventory. Do not claim success without runtime evidence.
10. Confirm V2 remains unaffected.

## Related current architecture work
V2 cockpit work is separate and should not be mixed into this PR. V2 desired state is OFF -> ARMED -> LIVE -> BLOCKED with preflight amount/notional and GO LIVE. Architecture ledger: `docs/AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md`; deep audit: `docs/AEN_ARCH18_DEEP_AUDIT_2026-10-01.md`; audit index: `docs/AEN_ARCH18_AUDIT_INDEX_2026-10-01.md`.

## Working style requested by Ove
Make an internal work list and execute several blocks continuously. While GitHub CI/Railway deploys, continue independent work and poll again. Do not stop merely to report that CI is running. Return to Ove when the block is actually complete or when a genuine product decision is needed.
