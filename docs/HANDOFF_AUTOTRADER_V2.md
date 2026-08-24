# Handoff — AutoTrader v2

## Mission

Own execution and risk control as a subsystem separate from PriceGauger analysis. AutoTrader receives explicit trade intents, validates them, sizes them, prechecks them with Saxo, requires the appropriate confirmation, submits them, and tracks execution/position state.

Long-term architecture may support full trading-bot capability, but that is explicitly not the current development target. Build today's manual execution/risk layer so later automation can plug in without architectural rework.

## Current safety posture

- Manual entry/buy/sell remains SIM-only and requires validation, Saxo precheck and explicit confirmation.
- LIVE capability is restricted to closing/reducing an already-open position that the user explicitly enrolled with Auto-manage.
- LIVE close requires LIVE environment, a separate code gate, an armed execution motor and an exact per-position enrollment match.
- RiskControl is an execution-adjacent decision layer, not a dry-run: it produces auditable close signals but never submits an order itself.
- The canonical default hard stop is −2% of the traded product's own position return. Existing persisted configuration is never overwritten by a deployment default.
- MACD remains dry-run only and has no execution authority.
- No strategy or AI may bypass AutoTrader validation/precheck/guardrails.
- Saxo order execution is an AutoTrader responsibility, not a TradingDesk or analysis-layer responsibility.

## Architectural position

```text
PriceGauger analysis
      ↓
Human / future AI decision
      ↓
structured trade intent
      ↓
AutoTrader
  validation
  risk limits
  product sizing
  Saxo precheck
  confirmation
  submission
  execution state
  position management
      ↓
Saxo SIM / later explicitly approved environment
```

## Core contracts to own

AutoTrader should expose explicit, testable contracts for:

- trade intent;
- market/instrument/product identity;
- side and requested exposure;
- sizing result;
- maximum bid/buy/exposure constraints;
- stop-loss and take-profit policy;
- precheck result;
- confirmation requirement/state;
- submission result/order identity;
- current position state;
- exit/reduction intent;
- audit/decision provenance.

## Risk controls

The subsystem should support bounded configuration rather than hidden judgment. Expected controls include maximum position size/exposure, maximum per-trade capital, stop-loss, take-profit, and later controlled trailing/reduction logic.

Potential later modifiers include gradual profit-taking as a move matures, reducing exposure as the thesis deteriorates, and trailing protection. These should be explicit policy modules with tests, not free-form AI behavior.

## Relationship to AI

A future AutoTrader AI may act as a decision companion or strategy agent. It can consume selected PriceGauger information channels such as TA-only, Technical Interpreter, CrossMarket, regime, macro/news, scheduled reports, and later position/account state.

Its output should include:

- structured decision specification used by backend logic;
- short human-readable reasoning for the frontend/activity ticker;
- explicit information channels/recipe used;
- confidence/uncertainty and invalidation conditions where relevant.

The human-readable monologue is explanatory. The structured decision record is authoritative.

AI can propose an action; AutoTrader still owns whether that action is permissible and executable.

## Strategy experimentation

Once manual execution is stable, the safest first automation experiments are deterministic and small: for example, a bounded SIM account running a simple technical rule such as 30m MACD cross-up entry and 15m MACD cross-down exit.

This creates a control experiment. Additional PriceGauger layers can then be enabled one by one and compared using real outcomes rather than intuition.

## Position management

Position management should eventually be event/state driven: entry, protection, partial reduction, take-profit, stop, thesis deterioration, manual intervention, and close. Avoid coupling this lifecycle directly to one analysis recipe.

## Working protocol

Start from fresh `main`, one bounded capability per branch/PR. Preserve SIM guardrails. Add explicit tests for every risk and state transition. Never weaken a guardrail merely to make a UI or test pass. Keep provider/Saxo errors observable and fail closed on ambiguous execution state.

## Immediate next priorities

1. Finish and harden the manual execution state machine from TradingDesk through Saxo SIM.
2. Formalize configurable risk policy: max capital/exposure, stop-loss, take-profit, confirmation requirements.
3. Add durable order/position state and restart reconciliation.
4. Add explicit partial exit/reduction contracts before attempting dynamic trailing policies.
5. Expose clean read models back to TradingDesk.
6. Only after stable manual operation: introduce a tiny deterministic SIM strategy runner.
7. Only after that: allow an AI strategy/companion to consume selected PriceGauger channels under the same risk envelope.

## Out of scope for now

No unrestricted autonomous trading, no live-money activation by implication, no AI-defined risk limits, and no hidden direct Saxo path outside AutoTrader.
