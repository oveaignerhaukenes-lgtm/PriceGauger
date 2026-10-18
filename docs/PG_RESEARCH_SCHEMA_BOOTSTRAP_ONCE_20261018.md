# Research-only V2 schema bootstrap once (2026-10-18)

Measured production pressure: PostgreSQL roughly 0.9 vCPU and Saxo
market stream roughly 0.64 vCPU on a trailing 24-hour sample. This is
not a claim about the isolated DDL contribution.

MACD dry-run, Fast15 shadow, MTF entry shadow and Cocktail Mode #1 shadow
each execute PostgreSQL \`CREATE TABLE IF NOT EXISTS\` DDL in:
1. Their \`run_*_forever\` bootstrap (once per process).
2. Their \`run_*_cycle\` on every scheduled 30–60s iteration.

The second DDL pass is redundant while the same research process stays up.
Each \`run_*_cycle\` now takes optional \`schema_prepared=False\`:
- default \`False\`: direct invocation still checks/creates tables,
  preserving existing ad hoc/CLI/tests caller semantics.
- long-running worker: performs \`ensure_*_schema\` once **before the loop**
  and passes \`schema_prepared=True\` to every scheduled cycle.
- schema/bootstrap failure before loop remains fail closed, unchanged.
- research process restart calls schema bootstrap again.

No schema migrations, table data, trade signals, research calculations,
market data ingestion, risk checks, Saxo LIVE, order guard, or V3 logic change.
No production flags or cadence changes. Tests verify all four direct-call
and long-running worker paths.

Caveat: If an operator externally drops a research table while a worker
is already running, the next research cycle will surface missing table
errors until the worker restarts, rather than re-creating it automatically.
Table removal in production should occur only as a controlled migration.

Next: compare DB CPU and statement rates over a matched active market
window, inspect \`pg_stat_statements\` (read-only if already enabled)
and properly repair invalid Natural Gas Saxo UIC using actual reference
data, not a guessed substitute. Related #735, #737, #738.
