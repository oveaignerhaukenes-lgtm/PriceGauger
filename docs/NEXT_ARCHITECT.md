# Next architect (current entry point)

**Start with the authoritative [2026-10-13 handoff](AEN_ARCHITECT_HANDOFF_2026-10-13.md).**

It supersedes the 2026-10-09 handoff on current deployments, LIVE whipsaw, AI/Live-Sim, and the recovered 20 GB PostgreSQL volume. Its production observations are timestamped snapshots, not permanent assertions.

**Highest priorities:**
1. Re-read LIVE runtime and Saxo durable pending-order reconciliation (Tech100-C had `PENDING` at the last check).
2. Verify Tech100-B’s explicitly consented LIVE whipsaw, **not** assumed enabled on other accounts or on gold.
3. Check the current Saxo instrument/account binding before interpreting “gull” or Hvelvet; new LIVE modifications require exact per-instance authorization.
4. Keep AI/Hyper Stochastic FULL execution rights restricted to PAPER, validate real quote availability and causal results.
5. Defer backup/cleanup/retention changes until the user explicitly schedules that separate maintenance session.

Working discipline:

```text
read latest handoff
→ refresh main + GitHub PRs
→ check Railway deploy SHA and actual runtime/Saxo state
→ plan bounded branch
→ CI
→ guarded merge
→ verify Railway deploy and logs
```

Minimal project bootstrap: [2026-10-06 bootstrap](PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md).

Older technical detail **only when relevant**:
- [2026-10-09 handoff](AEN_ARCHITECT_HANDOFF_2026-10-09.md)
- [LIVE Whipsaw/Volatility Pause](V3_LIVE_WHIPSAW_VOLATILITY_PAUSE_2026-10-13.md)
- [Context AI multi-strategy LAB](LIVE_SIM_AI_CONTEXT_MULTISTRATEGY_2026-10-13.md)
- [Architecture cleanup ledger](AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md)
- [2026-10-06 architecture handoff](AEN_ARCHITECT_19_HANDOFF_2026-10-06.md)

Do not preload the full historical handoff archive or long-form `CURRENT_STATUS.md` unless a specific task requires it.
