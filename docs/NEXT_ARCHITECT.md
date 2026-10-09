# Next architect

Start here:

**[docs/AEN_ARCHITECT_HANDOFF_2026-10-09.md](AEN_ARCHITECT_HANDOFF_2026-10-09.md)**

This is the current authoritative handoff after the October 8–9 V3 LIVE strategy cohort, Aen#2/Aen#2.1 work, cumulative margin-cap repair, marker repair and strategy-context reset hardening.

Then use:

**[docs/PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md](PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md)**

for the minimal project-wide architecture/bootstrap context.

Working rule:

```text
read current handoff
→ refresh main
→ inspect current Fleet/runtime before mutation
→ inspect only the code/tests relevant to the requested change
→ bounded branch
→ CI
→ guarded merge
→ verify exact Railway SHA
→ inspect runtime evidence
```

Do not preload the full historical handoff archive or the old long-form `CURRENT_STATUS.md` unless a concrete question requires it.

Deeper architecture references, only when needed:

- `docs/AEN_ARCHITECTURE_CLEANUP_LEDGER_2026-10-01.md`
- `docs/AEN_ARCHITECT_19_HANDOFF_2026-10-06.md`
- `docs/AEN_CANONICAL_MODULE_MAP_2026-10-02.md`

Immediate product direction: preserve the current multi-account LIVE test, keep Aen#2/Aen#2.1 stable unless explicitly asked to change them, and treat the next likely strategy enhancement as a bounded Impulse/Reversal modifier rather than another base-strategy rewrite.
