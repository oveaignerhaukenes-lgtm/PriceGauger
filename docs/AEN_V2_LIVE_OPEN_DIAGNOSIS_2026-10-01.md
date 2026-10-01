# Aen handoff — Autotrader V2 LIVE OPEN diagnosis

Date: 2026-10-01
Scope: diagnosis only; no runtime mutation was performed.

## Executive result

The recent V2 symptom is **not Saxo cancelling an accepted order** and is **not the stale-working-order execution guard cancelling a `pg-open-*` order**. The observed V2 OPEN is blocked **before broker submission** by the V2 entry policy because the required margin envelope is not active.

Concrete runtime sequence observed during diagnosis:

- `20:27:10` — V2 produces `TARGET_SHORT`; execution request is created (`request_created=True`).
- `20:27:14` — LIVE OPEN path blocks the request with `MARGIN_ENVELOPE_NOT_ACTIVE`.
- No broker-accepted OPEN precedes that block, so there is no Saxo order for the guard to cancel in this sequence.

This matches the user's visible symptom: V2 appears to initiate/attempt trading but remains FLAT and retries rather than establishing the intended position.

## Code path checked

### `autotrader_execution_guard_v1.py`

The stale working-order guard was investigated because its behavior initially fit the symptom. It sweeps working `pg-open-*` orders and can cancel a broker order when `_request_current()` becomes false. A request can become stale if, among other conditions:

- the strategy enrollment has a newer `updated_at` than the request `created_at`; or
- a newer strategy evaluation with a non-null `intent_id` has `signal_at > request.signal_at`.

However, this guard only matters once an OPEN has reached broker-working-order state. The runtime evidence above shows the failing V2 attempt never reached that state.

### V2 LIVE OPEN / entry policy

The blocking path is the V2 entry-policy / margin-envelope requirement. `require_entry_policy_v2()` requires an active pilot margin configuration before an OPEN may proceed. For the failing V2 attempt, that prerequisite resolves false and the OPEN is rejected with `MARGIN_ENVELOPE_NOT_ACTIVE` before Saxo submission.

## Recommended fix

Do **not** solve this by manually enabling an arbitrary margin multiple in Railway/DB as a one-off. That would hide the lifecycle bug and make the next strategy/account enrollment vulnerable to the same deadlock.

Preferred repair:

1. When V2 is armed/enrolled for LIVE with a defined capital budget/exposure configuration, create or activate the corresponding margin-envelope configuration as part of the same lifecycle.
2. Keep the existing LIVE OPEN entry-policy check as the fail-closed backstop.
3. Make the UI/runtime state explicit: if V2 is armed but its envelope is absent/inactive, expose that state rather than making the strategy look active while every OPEN is silently blocked.
4. Add regression coverage for: arm/enroll -> envelope active -> request created -> precheck -> broker submit; and for deliberate envelope disable -> deterministic `MARGIN_ENVELOPE_NOT_ACTIVE` without broker submission.
5. Re-run a low-size V2 LIVE attempt and verify a concrete transition through broker acceptance/reconciliation. Compare against V3, which is currently trading successfully in the same environment.

## Important separation from V3

V3 is currently reported by the user to be performing very well. Avoid broad changes to shared execution behavior unless required. Prefer a narrowly scoped V2 lifecycle/configuration repair, preserving the working V3 path.

## Secondary finding: Brent feed

During the same investigation, the Saxo market-data diagnostics showed:

- Tech100: realtime (`DelayedByMinutes=0`).
- The currently configured Brent futures feed: 15-minute delayed.

Repo configuration currently includes Brent as a Saxo `ContractFutures` instrument (`LCOV6`, UIC `43660942`, description `Brent Crude - Oct 2026`). Existing Saxo infrastructure already supports generic discovery, InfoPrice diagnostics and streaming, so no new streaming subsystem should be needed. The next step for the Energy Radar work is to discover/check the appropriate Brent CFD/current instrument and its entitlement, then select a realtime proxy if available.

## Suggested next-architect order

1. Repair V2 arm/enrollment -> margin-envelope lifecycle.
2. Add targeted regression tests.
3. Deploy and inspect LIVE logs through one low-size V2 OPEN/reconciliation cycle.
4. Leave V3 behavior untouched unless shared code demonstrably requires adjustment.
5. Then continue Brent realtime-proxy discovery for Energy Radar.
