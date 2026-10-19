# PriceGauger agent instructions

Before changing code:
1. Read `PROJECT_STATE.md`.
2. Inspect fresh `main`, relevant modules/tests and current open PRs.
3. For deployment or LIVE claims, check Railway runtime and authoritative Saxo/DB evidence.
4. Treat old handoffs as historical references only.

During work: keep changes bounded and tested. Preserve execution authority, margin, ownership, reconciliation and no-blind-retry invariants.

Before completing any nontrivial PR: update the `PROJECT_STATE.md` active-work ledger and decisions where appropriate; link the PR or changed module. Do not claim a deployment or broker fill without evidence. Prefer one concise state line over another handoff document.

Do not commit secrets, personal financial/account records or full production logs. Automated `docs/PROJECT_CHANGELOG.md` only records Git history.
