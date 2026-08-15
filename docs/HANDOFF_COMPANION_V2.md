# Handoff — Analyst Companion v2

## Mission

Own the human-facing, session-scoped AI analyst that follows one selected market alongside the user and provides concise technical interpretation as persisted PriceGauger state changes.

The Companion is an analyst, not an adviser, execution agent or forecasting authority.

## Current v1 contract

Start from `docs/ANALYST_COMPANION_V2.md` and the implementation in:

- `analyst_companion_v2.py`
- `companion_runtime_v2.py`
- `openai_companion_provider.py`
- `companion_ui_v2.py`

The current frontend integration lives in `pages/9_V2_Technical.py`.

## Invariants

1. Technical Core remains deterministic and authoritative for the baseline forecast.
2. Companion may interpret Technical Core and observed canonical price history but must not silently mutate the forecast.
3. Numeric support/resistance in structured Companion state must be grounded in deterministic system-derived candidates, not invented by the model.
4. A session is bound to one market and retains bounded continuity across new snapshots.
5. Same-snapshot UI rerenders must not trigger repeated analysis calls.
6. No Saxo execution, AutoTrader command, order, position sizing, leverage or trade-authority path may enter this subsystem.
7. `Ask Companion` is contextual analysis Q&A, not an execution interface.
8. Any future DB persistence is a separate bounded capability reviewed with Database ownership.
9. Any future use of Companion output as a forecast refinement is a separate explicit recipe/layer capability.

## Immediate verification after landing

On Railway with `OPENAI_API_KEY` configured:

1. Open `V2 Technical` and select an active market.
2. Press **Activate Companion**.
3. Confirm one structured analysis appears and the session remains active across UI refreshes.
4. Confirm repeated 15-second fragment rerenders on the same `as_of` do not generate a new analysis.
5. When a new Technical Core snapshot arrives, confirm `what_changed` and commentary refresh.
6. Confirm displayed support/resistance corresponds to system-derived candidate IDs.
7. Ask a technical question via **Ask Companion** and verify contextual continuity.
8. Switch markets and verify the active session does not silently follow; the user must end the session first.
9. End the session and confirm no further provider calls are made.

## Good next capabilities

Prioritize evidence from real use. Likely improvements include better deterministic level/zone extraction, richer change detection, compact event timelines, session persistence if users value history, and optional additional read-only inputs such as cached Technical Interpreter or future CrossMarket context.

Do not add execution or autonomous trading merely because the Companion becomes more capable. Those remain separate subsystems with separate authorization boundaries.
