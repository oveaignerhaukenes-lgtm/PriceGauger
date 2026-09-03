# PriceGauger — Next Architect

Updated: 2026-09-03

The authoritative handoff is now:

**[`docs/ARCHITECT_HANDOFF_2026-09-03.md`](ARCHITECT_HANDOFF_2026-09-03.md)**

Read that document in full before changing AutoManager, strategy runtime, Saxo execution, or futures identity/lifecycle behavior.

## Starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Canonical `main` at handoff creation:

`c45de4a720aafaefcca8e1a6d8821d12f807bf6a`

Always refresh from current `main` before branching; the SHA above is the exact handoff baseline, not a permanent pin.

## Immediate orientation

Current LIVE pilot is US Tech 100 / Saxo UIC 4912 (`CfdOnIndex`) with `macd-mtf-30-10-5-long-short-v1` as the LIVE controller. The Saxo lifecycle has recently been hardened around net-position direction, close/P&L provenance, carried flip settlement, pilot resume and Postgres evaluation.

The strategic center has shifted toward **Cocktail Mode #1**, currently SHADOW ONLY. Cocktail observes forming 5/10/15/30m MACD on the canonical 1m clock and treats the actual cross timestamp—not enclosing bar close—as the coherent event basis. Its modes are `NORMAL`, `SHOCK`, `TREND_LOCK`, and `WHIPSAW`, with `FLAT` as an active state.

Do not claim Cocktail profitability from the initial sample even though early observations are promising. Continue collecting evidence across regimes and refine it with direct price/regime confirmation.

## Immediate next work

1. Fix TradingDesk’s misleading `Aktiver AutoManager` UI when the exact product already has an active LIVE controller. Backend one-controller enforcement is already correct.
2. Observe a natural MTF LIVE reversal and verify the full `signal → CLOSE → confirmed FLAT → settled P/L → opposite OPEN` chain after PRs #273/#274.
3. Fix Cocktail shadow `sp500 CFD: invalid 5m ATR`.
4. Add explicit MACD zero-line/regime + direct-price confirmation / momentum-price divergence to Cocktail shadow.
5. Continue strategy comparison across different regimes before any Cocktail LIVE promotion.
6. Build an explicit futures **ContractLifecycle/Rollover** layer before autonomous management of expiring futures.
7. Delay the broad architecture cleanup until the strategy end-state is clearer.

## Futures rollover rule in one sentence

Keep the **economic market** stable (e.g. Brent/Gold) while treating every concrete futures contract/UIC as a separate execution epoch; never silently mutate a LIVE controller from one UIC to the next, and never let a contract-roll price gap masquerade as a strategy signal.

Full rollover requirements, safety invariants, recent PR rationale, Railway identities, Cocktail/Gin Tonic direction, WorkspaceState status, and orientation files are all documented in `ARCHITECT_HANDOFF_2026-09-03.md`.
