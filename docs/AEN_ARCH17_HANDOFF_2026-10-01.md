# AEN Architect 17 handoff — 2026-10-01

## Executive state

Architect 17 repaired several independent V2 blockers and the chart execution-provenance path. The final root cause supplied by the parallel diagnosis was `MARGIN_ENVELOPE_NOT_ACTIVE`: V2 produced a valid target and execution request but blocked before Saxo submission because LIVE activation and the pilot Margin Envelope had separate lifecycles.

PR #613 is merged as commit `34ba658aefdf66f27b5d38866811379acb03b2e8`. GitHub CI passed. All four Railway production services reached SUCCESS on that commit. No V3 execution behavior was changed by #613.

## Final V2 lifecycle repair — PR #613

Canonical `set_auto_manage_enabled_v1(enrollment, True)` now provisions a missing pilot Margin Envelope *before* strategy authority is persisted.

Defaults are the same existing V2 UI defaults:
- `max_effective_leverage = 5.0`
- `minimum_free_capital = 0.0`
- `enabled = True`

Important semantics:
- missing envelope = lifecycle gap, auto-provision on LIVE ON;
- existing enabled envelope = preserve it;
- explicitly disabled envelope = fail closed with `MARGIN_ENVELOPE_DISABLED`; do not silently re-enable;
- LIVE OFF never creates or enables an envelope;
- `require_entry_policy_v2()` remains unchanged as the final runtime backstop;
- bootstrap and TradingDesk LIVE ON both use the canonical setter, so both get the lifecycle fix.

Regression file: `tests/test_v2_atomic_live_activation_v1.py`.

## What user should do next

Refresh TradingDesk. If V2 is OFF, the user should toggle `ENGINE V2 · LIVE` ON once. Do not mutate that authority flag directly in DB. The old guard implementation may have persisted OFF before the authority/guard-state separation was repaired.

After LIVE ON, inspect PriceGauger-stream logs for the next V2 signal. Expected chain:

`strategy evaluation -> TARGET_LONG/SHORT -> request_created=True -> entry policy -> sizing/Saxo precheck -> broker accepted -> reconciliation`

`MARGIN_ENVELOPE_NOT_ACTIVE` should no longer occur for a missing envelope after this explicit LIVE ON. If another blocker appears, diagnose that exact blocker; do not bypass the entry policy wholesale.

## Earlier Architect 17 repairs

### PR #607 — direction admission

V2 was first blocked by `NOT_IN_PG_PRODUCT_UNIVERSE` because product admission was stored direction-specifically. The repair can carry verified exact-account/product safety admission across LONG/SHORT while final direction-specific Saxo sizing/precheck still applies.

### PR #609 — chart execution provenance

Root cause of missing V3 chart arrows: durable V3 broker OrderIds were not known to manual Saxo marker sync, so real V3 fills were being classified as manual. The AutoTrader marker projection also did not read durable V3 executions.

Current marker contract:
- manual Saxo: green/red directional arrow + compact `M`;
- V2 AutoTrader: blue arrow, no text;
- V3 AutoTrader: purple arrow, no text;
- durable PG broker OrderIds are excluded from manual classification;
- reconciled durable executions are projected with V2/V3 provenance;
- previously persisted false-manual rows are filtered at read time.

### PRs #610/#611 — manual position provenance

V2 can adopt a broker-audit-proven intentional manual adjustment for the exact account/UIC/AssetType. The fallback tolerates Saxo PositionId/NetPositionId rollover after manual resize/close/reopen. Durable PG broker OrderIds remain excluded.

### PR #612 — authority vs guard state

User LIVE preference and execution-guard interlock are separate state dimensions. A guard no longer rewrites the user's persistent AutoTrade preference to OFF. LIVE ON cannot bypass an active guard. Proven resolution clears only the matching guard interlock.

## Known V2 UI cleanup still worth doing

There are still overlapping generations of control surface:
- the authoritative `ENGINE V2 · LIVE` toggle in `tradingdesk_automanager_simple_v1.py`;
- family/timeframe builder with a `Bruk <strategy>` button in `tradingdesk_strategy_family_ui_v1.py`;
- the older detailed execution-gate UI in `tradingdesk_autotrade_entry_gate_v2.py`, including explicit Margin Envelope controls.

Do not remove the runtime policies. Consolidate the *control plane* so normal operation is conceptually:

`account + strategy + timeframe + capital/exposure -> ENGINE V2 LIVE ON`

and advanced settings remain optional. A selected strategy/timeframe should be authoritative without a confusing second activation model. The UI should expose a concrete BLOCKED reason when a runtime prerequisite fails rather than looking LIVE while execution is impossible.

## V2/V3 account boundaries

- V2/Lager account: `1084854INET`
- V3/Autotrader account: `1068427INET`
- V2 pilot observed in this investigation: `5b056d92-8780-57a4-884f-e263008966da`
- V3 pilot: `b6008676-ec57-50e9-9cbf-3b0577c643ab`

Never let one motor manage the other account/product boundary. V3 was reported by the user as performing well; avoid broad shared execution changes unless evidence requires them.

## Production / Railway

Project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`
Production environment: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`

Services:
- Spring-Trade-Engine `254b205b-1633-4c69-aa84-486a0fa6f052`
- PriceGauger-stream `0be7cd65-533f-4882-9b81-efeda5b35153` — V2 runtime logs
- pricegauger-web `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- PriceGauger-worker `5267feed-b5cb-4f85-a24a-0c5124664b59` — V3 runtime logs

At handoff all four deployments for commit `34ba658...` were SUCCESS. A log query after deployment showed no new `MARGIN_ENVELOPE_NOT_ACTIVE`, but V2 had not yet been explicitly toggled ON by the user after the deployment, so do not claim a broker OPEN/reconciliation has been verified yet.

## Parallel diagnosis document

Read `docs/AEN_V2_LIVE_OPEN_DIAGNOSIS_2026-10-01.md`. It contains the decisive runtime evidence from 20:27: V2 generated `TARGET_SHORT`, created the request, then blocked pre-broker on `MARGIN_ENVELOPE_NOT_ACTIVE`.

It also contains a secondary Energy Radar finding: the configured Brent futures feed was 15-minute delayed while Tech100 was realtime. Brent realtime CFD/proxy discovery remains future work.

## Working method requested by user

Keep the thread alive while CI/deploy runs. Poll through completion, inspect failures, repair and retry instead of stopping at “CI is running”. Make engineering decisions directly when repo/log evidence is sufficient; ask the user only for genuine product/external decisions. Never claim a Saxo execution without broker/runtime evidence.
