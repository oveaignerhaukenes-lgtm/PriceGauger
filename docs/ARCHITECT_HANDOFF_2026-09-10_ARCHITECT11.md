# PriceGauger — Architect 11 handoff

Date: 2026-09-10

## Start here

The immediate production bug is now diagnosed precisely, but **the production fix has NOT been implemented/deployed yet**.

Do not broaden the change. Make the smallest possible fix, run CI, merge only green, wait/poll Railway until production is deployed, then ask Ove for one controlled BUY click in PriceGauger and follow the production logs through the entire reversal.

**Important workflow requirement from Ove:** do not end a turn after saying you will do the next technical step. Continue through the tool workflow yourself: inspect -> edit -> commit/PR -> CI -> fix failures -> green -> merge -> Railway deploy -> production verification. Poll CI/deployment as needed. Stop only when a real user action is required or a new trading/risk decision needs approval.

## Authoritative current state

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Last known production/diagnostics main before the accidental test-only commit:
- `567ad3e2a86199ed7e27b93e25cc21dbaa937174`
- `Execution: expose Saxo CLOSE precheck ErrorInfo (#366)`

PR #366 merged and its diagnostics deployed successfully.

There is now also a **test-only commit directly on main**:
- `e474daa1398bc578c7e0e09129186cab917df315`
- `Test CLOSE amount float normalization`

It adds `tests/test_autotrader_close_amount_precision_v1.py`, asserting that `_close_payload()` converts the observed noisy amount `0.009999999999999953` to `0.01`. At handoff, the implementation still returns `float(observation.amount)`, so this test is expected to fail until the minimal fix is made.

A branch was created:
- `architect11/close-amount-precision-fix`

At handoff it points at `e474daa...` and contains no production fix beyond main.

## Root cause — confirmed from live Saxo diagnostics

The failing CLOSE path was no longer speculative after PR #366. PriceGauger sent a CLOSE BUY with an amount equivalent to:

```text
0.009999999999999953
```

instead of:

```text
0.01
```

Saxo precheck rejected it with `OtherError`; the returned message states that the number of decimals for the fractional amount exceeds the configured value.

Therefore the immediate failure is a binary floating-point/amount precision problem, not evidence of a MACD problem, netting-model problem, permission problem, or a reason to remove Saxo precheck.

## Minimal fix requested by Ove

Ove explicitly wants **the smallest possible change first**, then a live test before doing anything more.

Current relevant code in `autotrader_live_close_v1.py`, `_close_payload()`:

```python
"Amount": float(observation.amount),
```

Change only the amount construction sufficiently to remove binary float noise so the observed value becomes Saxo-valid `0.01`. Prefer the narrowest defensible normalization; do not refactor execution architecture in this PR.

The regression test already on main is:

```python
from types import SimpleNamespace

from autotrader_live_close_v1 import _close_payload


def test_close_payload_removes_binary_float_noise_from_amount() -> None:
    observation = SimpleNamespace(
        direction="Sell",
        amount=0.009999999999999953,
        asset_type="CfdOnIndex",
        uic=4912,
    )
    payload = _close_payload(account_key="account-key", observation=observation, external_reference="test")
    assert payload["Amount"] == 0.01
```

Do not modify MACD, target selection, reversal semantics, sizing policy, precheck behavior, FLAT confirmation, or other safety gates merely to make this test pass.

## Required live verification after deploy

Do **not** ask Ove to touch Saxo manually. Once the fix is green, merged, deployed and verified on Railway, tell him explicitly to press **BUY in PriceGauger** once.

Expected lifecycle from the current SHORT state:

```text
USER TARGET LONG
-> CLOSE existing SHORT by BUY existing amount (expected 0.01)
-> Saxo precheck OK
-> durable attempt before broker POST
-> broker close order accepted
-> exact Saxo state confirms FLAT
-> only then OPEN desired LONG
-> Saxo confirms LONG
```

Watch production logs during this. If it fails, use the diagnostics already deployed to identify the next exact boundary; do not guess.

## Execution contract / safety invariants

Pilot product: US Tech 100 NAS, Saxo UIC 4912.
Pilot strategy: `macd-2m-flip-control-shadow-v1`.

Core reversal invariant:

```text
desired LONG/SHORT
-> compare exact Saxo product state
-> CLOSE opposite exposure
-> confirm Saxo FLAT
-> OPEN desired side
```

Never do a one-order reversal that skips confirmed FLAT. Never allow simultaneous intended LONG+SHORT exposure. `SUBMITTING` / `UNCERTAIN` close state blocks re-entry. Durable attempt must exist before actual broker POST. Position Guardian/RiskControl is defensive only and may not originate/increase exposure. Realized P/L accounting is not execution authority and must not block reversal.

Target Saxo netting semantics based on current understanding:
- SHORT 0.01 -> BUY 0.01 -> confirm FLAT -> BUY desired LONG size.
- LONG -> SELL existing amount -> confirm FLAT -> SELL desired SHORT size.
- `IsForceOpen=False`.
- Saxo `PositionNettingMode` is expected to be `Intraday`.

The separate Saxo `orders/precheck` call is not itself a sacred invariant, but **do not remove it because of this incident**: here it correctly prevented submission of a malformed amount and gave us the root cause.

## Diagnostics added in PR #366

New module: `autotrader_precheck_diagnostics_v1.py`.

Failed CLOSE prechecks now safely expose/log:
- `PreCheckResult`
- `ErrorInfo.ErrorCode`
- `ErrorInfo.Message`
- whether disclaimers exist
- response key names
- close side, amount, UIC, AssetType, PositionId where appropriate

It deliberately does not log AccountKey, ExternalReference, disclaimer tokens, full payload, or full response.

Useful log phrase:

```text
strategy CLOSE precheck blocked
```

and fields:

```text
error_code=
error_message=
```

## Railway

Project: `grateful-reflection`
Project ID: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`
Production environment: `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`

Services:
- Stream: `0be7cd65-533f-4882-9b81-efeda5b35153`
- Worker: `5267feed-b5cb-4f85-a24a-0c5124664b59`
- Spring engine: `254b205b-1633-4c69-aa84-486a0fa6f052`
- Web: `38f57908-1f7a-40ce-9bf4-abcdf43fe429`
- Postgres: `a7a66447-8138-4ea9-94b0-5df0c291f337`

PR #366 Stream deployment was `7ab1dbee-8c54-42cc-9702-bbe290123f4d` for commit `567ad3e...`; diagnostics were observed live afterward.

After merging the precision fix, poll the new Railway deployment to a terminal state. Do not merely report BUILDING and stop.

## Recent request behavior / reproduction context

Before diagnostics, the pattern was:

```text
MACD/USER LONG intent
-> execution request created
-> CLOSE worker armed
-> Saxo trade/v2/orders/precheck returns PreCheckResult=Error
-> no order POST
-> SHORT remains
```

Multiple manual PG BUY/reversal requests reproduced the same failure. Ove intentionally avoided manual Saxo intervention so the state remained useful for diagnosis.

## Other open work — after the amount fix/live test

Do not mix these into the precision fix.

1. SQL placeholder bug in `autotrader_execution_guard_v1.py` path via `_pause()` -> `set_auto_manage_enabled_v1()`: psycopg3 error about invalid literal `%` (`only '%s', '%b', '%t' are allowed as placeholders, got '%'`). Needs a separate bounded regression/fix, fail-closed Manage pause preserved.

2. UI/chart PR #365: `architect11/chart-gesture-current-main`, head previously `4b4b910f7b0028cf8494e75ba236346244a7fea7`, title `TradingDesk: chart owns in-chart gestures`. Lower priority than execution.

3. Marker semantics later: PG/AutoTrader execution should be arrows; manual/external Saxo intervention should be squares, same directional color, persisted origin `MANUAL_EXTERNAL`. Do not fabricate manual events from ambiguous net changes.

4. Pending reversal UX: blue `Brukermål pågår` box should eventually show age/block reason rather than silently disappearing.

5. Determine whether chart arrows are signal markers or actual execution markers before treating a missing LONG arrow as a bug. Backend LONG intent existed while CLOSE failed, so no execution arrow may be correct if arrows mean trades.

## Prior useful merged work

PR #359: isolated P/L reconciliation from live execution authority; accounting settlement must not block reversal.

PR #362: exposed pending CLOSE lifecycle, arm state, pending age/reasons; disarmed pending is no longer silent.

PR #366: safe Saxo CLOSE precheck ErrorInfo diagnostics; this produced the exact root cause above.

## Pilot/accounting context

Pilot seed: 500 NOK.
Recent UI snapshot before this handoff showed roughly:
- Equity 643.95 NOK
- realized +143.95 NOK (+28.8%)
- 52 trades
- current actual state SHORT 0.01

Treat those values as historical UI context, not current broker truth; re-observe Saxo before making execution decisions.

## Non-blocking known issues

- OpenAI API production calls have shown 429 insufficient quota; unrelated to this execution failure.
- Natural Gas stale/rollover/warmup issues should remain fail-closed.
- S&P Cocktail invalid 5m ATR should not be papered over.

## First actions for Architect 12

1. Inspect current `main` and confirm `e474daa...` plus the failing regression test.
2. Implement the **minimal amount normalization** in `_close_payload()` only.
3. Run/observe CI; fix only relevant failures.
4. Merge only green.
5. Poll Railway deployment until SUCCESS/FAILED; if failed, inspect and repair.
6. Verify production is running the new commit.
7. Then ask Ove for exactly one **PG BUY** click.
8. Follow logs through CLOSE -> FLAT -> OPEN and report the observed broker lifecycle.
9. Only after that decide whether another execution change is necessary.

The key principle for this takeover: **we have a concrete root cause. Fix that one thing first and test reality before redesigning anything.**
