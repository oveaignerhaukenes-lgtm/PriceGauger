# Reversal / Impulse shadow observer — first bounded candidate (2026-10-09)

## Scope

This is a research-only, deterministic *counterfactual* for Aen#2 / Aen#2.1.
Module: `autotrader_v3_reversal_shadow_v1.py`.
It has **no LIVE or SIM registry entry**, imports into no worker/execution module, performs no I/O and has no order authority. The current four-account LIVE cohort and strategy bindings are unchanged.

## Hypothesis

A persistent accelerating counter-move can justify pausing builds, or defensively going FLAT, **before R formally crosses**, without permitting S to freely flip the strategy.

The observer compares a base target to a *proposed shadow target* for the existing broker inventory:

1. No position / insufficient R/S evidence: preserve the base target (no invented entry or signal).
2. Raw R has already crossed against the actual side: propose FLAT (this is an Aen#2.1 reference behavior, not new alpha).
3. Two adverse S slopes + R weakening, while R is still on the original side: pause **only same-side expansion**. Never undo the base strategy's existing REDUCE/CLOSE.
4. If the second adverse S move is at least 1.5x the first **and** raw R is within 1.5x its adaptive deadband from zero: propose FLAT, without an opposite-side probe.
5. No qualifying reversal evidence: preserve base target.

Thresholds are explicit provisional research hypotheses. They are **not** tuned or validated by the brief recent LIVE sample.

## Contract

- Inputs: exact current inventory, base strategy target, existing `StickyRegimeSnapshotV3` and `StickySignalSnapshotV3` (from canonical closed-bar data).
- Output: `ReversalShadowDecisionV3(action, base_target, shadow_target, reason, evidence flags)`.
- Never submit the shadow target to the broker.
- Neither Aen#2 nor Aen#2.1 is changed.
- No new mutable DB memory; decisions can be deterministically replayed.
- The observer must be called on a properly closed S bar, using R/S history cut off at that bar; do not feed it future bars.
- The observer presently has no production telemetry plumbing. A successful pure unit test does **not** establish trading performance or operational activation.

## Acceptance before any LIVE promotion

Replay matched canonical bars across trend, choppiness, false reversal, impulse/retrace, news shock and quiet regimes. Log both base and shadow target with evidence, gross/net P&L, turnover, worst drawdown, late exits, avoided adverse exposure and missed recovery. Include costs, spread, slippage assumptions, identical t0 and the same risk budget. Require out-of-sample benefit rather than optimising one reversal.

Promotion, if justified, must be a separately authorised bounded modifier with a clear UI runtime-ready flag, deterministic fail behavior and new integration tests. It must never acquire unrestricted opposite-side pyramiding authority, bypass capital/ownership gates or alter the existing Aen#2/Aen#2.1 control cohorts implicitly.
