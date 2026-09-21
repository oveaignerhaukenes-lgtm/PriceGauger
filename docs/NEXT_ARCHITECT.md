# PriceGauger — Next Architect

Updated: 2026-09-21

The authoritative handoff for **Arkitekt 13** is:

**[`docs/ARCHITECT_HANDOFF_2026-09-21_ARKITEKT13.md`](ARCHITECT_HANDOFF_2026-09-21_ARKITEKT13.md)**

Read that document in full before changing AutoManager, strategy-family parameters, LIVE execution, TakeProfit, the runtime watchdog, or the TradingDesk Lightweight chart.

## Starting point

Repository: `oveaignerhaukenes-lgtm/PriceGauger`

Authoritative `main` immediately before this documentation handoff branch:

`97561cdb32eaee5174fd3fb6d5105f26bac59ade`

This baseline includes:

- parameterized strategy families: MACD(N), Price + MACD(N), Price + Stoch
- timeframe presets + custom 1–240m for MACD/Price+MACD
- explicit SIM / LIVE / both activation
- generic `X + TakeProfit`
- Price + Stoch half-parade
- read-only runtime watchdog / flight recorder
- corrected MACD cross authority
- single-component live chart with forming-candle ownership
- FLAT/manual trade markers
- hardened CLOSE -> confirmed FLAT -> OPEN execution lifecycle

PR #417 provided full end-to-end family verification; its head passed GitHub **Tests #2574** successfully before merge.

All Railway production services were **SUCCESS** at handoff creation.

Always refresh from current `main` before branching. Older handoff documents are historical and must not override the Arkitekt 13 handoff or fresh source inspection.

## Immediate orientation

The next phase is no longer execution-foundation construction. It is:

1. validate the newly landed family UI and single-component live chart on the user's actual mobile production session;
2. consolidate family/modifier presentation so effective strategy identity is obvious everywhere;
3. extend/test family semantics only with shared SIM/LIVE cores;
4. use watchdog evidence for runtime anomalies instead of screenshot inference;
5. close or deliberately revive stale draft PR #405 after review.

Do not reintroduce cross-iframe chart updaters, score vetoes over confirmed MACD crosses, direct strategy-to-Saxo order submission, or strategy-key explosions for parameter/modifier combinations.
